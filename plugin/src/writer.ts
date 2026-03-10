import { appendFile, stat, rename, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type { DoctorRecord, PluginConfig } from "./types.js";
import { redact } from "./redact.js";

/**
 * Async JSONL writer with daily file naming and size-based rotation.
 *
 * Output files: <outputDir>/llm-doctor-YYYY-MM-DD.jsonl
 * Rotated files: <outputDir>/llm-doctor-YYYY-MM-DD.<n>.jsonl
 */
export class JsonlWriter {
  private dir: string;
  private maxSize: number;
  private shouldRedact: boolean;
  private capturePayloads: boolean;
  private maxPayloadSize: number;
  private ready: Promise<void>;
  private buffer: string[] = [];
  private flushing = false;

  constructor(config: PluginConfig) {
    this.dir = resolveDir(config.outputDir);
    this.maxSize = config.rotateMaxSize;
    this.shouldRedact = config.redactSecrets;
    this.capturePayloads = config.capturePayloads;
    this.maxPayloadSize = config.maxPayloadSize;
    this.ready = this.ensureDir();
  }

  /** Enqueue a record for async writing. Never blocks the caller. */
  write(record: DoctorRecord): void {
    let data: unknown = record;
    if (!this.capturePayloads && "payload" in record) {
      const { payload: _payload, ...rest } = record;
      data = rest;
    }
    if (this.shouldRedact) {
      data = redact(data);
    }

    let line = JSON.stringify(data);

    if (this.maxPayloadSize > 0 && line.length > this.maxPayloadSize) {
      // Truncate the serialised line and mark it
      line = line.slice(0, this.maxPayloadSize);
      // Ensure it's still parseable by wrapping in an envelope
      const truncated: Record<string, unknown> = {
        type: (record as DoctorRecord).type,
        ts: (record as DoctorRecord).ts,
        _truncated: true,
        _originalBytes: JSON.stringify(data).length,
      };
      line = JSON.stringify(truncated);
    }

    this.buffer.push(line);
    this.scheduleFlush();
  }

  // ---- internals ----

  private flushTimer: ReturnType<typeof setTimeout> | null = null;

  private scheduleFlush(): void {
    if (this.flushTimer) return;
    this.flushTimer = setTimeout(() => {
      this.flushTimer = null;
      void this.flush();
    }, 50);
  }

  private async flush(): Promise<void> {
    if (this.flushing || this.buffer.length === 0) return;
    this.flushing = true;

    try {
      await this.ready;
      const lines = this.buffer.splice(0);
      const filePath = this.currentPath();

      await this.rotateIfNeeded(filePath);
      await appendFile(filePath, lines.join("\n") + "\n", "utf-8");
    } catch {
      // Silently drop — plugin must never crash the Gateway
    } finally {
      this.flushing = false;
      if (this.buffer.length > 0) {
        this.scheduleFlush();
      }
    }
  }

  private currentPath(): string {
    const date = new Date().toISOString().slice(0, 10); // YYYY-MM-DD
    return join(this.dir, `llm-doctor-${date}.jsonl`);
  }

  private async rotateIfNeeded(filePath: string): Promise<void> {
    if (this.maxSize <= 0) return;
    try {
      const s = await stat(filePath);
      if (s.size < this.maxSize) return;

      // Find the next rotation index
      let idx = 1;
      while (existsSync(`${filePath}.${idx}`)) idx++;
      await rename(filePath, `${filePath}.${idx}`);
    } catch {
      // File doesn't exist yet — nothing to rotate
    }
  }

  private async ensureDir(): Promise<void> {
    if (!existsSync(this.dir)) {
      await mkdir(this.dir, { recursive: true });
    }
  }
}

function resolveDir(dir: string): string {
  if (dir.startsWith("~")) {
    return join(homedir(), dir.slice(1));
  }
  return dir;
}
