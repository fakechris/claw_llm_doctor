import { readFileSync, existsSync, statSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";
import type { PluginConfig } from "./types.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function resolveDir(dir: string): string {
  if (dir.startsWith("~")) {
    return join(homedir(), dir.slice(1));
  }
  return dir;
}

function todayDateStr(): string {
  return new Date().toISOString().slice(0, 10);
}

function currentLogPath(dir: string): string {
  return join(dir, `llm-doctor-${todayDateStr()}.jsonl`);
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function readLines(filePath: string): string[] {
  if (!existsSync(filePath)) return [];
  const content = readFileSync(filePath, "utf-8");
  return content.split("\n").filter((l) => l.trim().length > 0);
}

function countRecords(filePath: string): number {
  return readLines(filePath).length;
}

// ---------------------------------------------------------------------------
// openclaw doctor status
// ---------------------------------------------------------------------------

function runStatus(cfg: PluginConfig): void {
  const dir = resolveDir(cfg.outputDir);
  const logFile = currentLogPath(dir);
  const fileExists = existsSync(logFile);

  console.log("LLM Doctor Status\n");
  console.log(`  Output dir:        ${dir}`);
  console.log(`  Capture payloads:  ${cfg.capturePayloads ? "yes" : "no"}`);
  console.log(`  Redact secrets:    ${cfg.redactSecrets ? "yes" : "no"}`);
  console.log(`  Max payload size:  ${cfg.maxPayloadSize > 0 ? formatBytes(cfg.maxPayloadSize) : "unlimited"}`);
  console.log(`  Rotate max size:   ${cfg.rotateMaxSize > 0 ? formatBytes(cfg.rotateMaxSize) : "disabled"}`);
  console.log();
  console.log(`  Current log file:  ${logFile}`);

  if (fileExists) {
    const st = statSync(logFile);
    const records = countRecords(logFile);
    console.log(`  File size:         ${formatBytes(st.size)}`);
    console.log(`  Record count:      ${records}`);
  } else {
    console.log(`  File size:         (file does not exist yet)`);
    console.log(`  Record count:      0`);
  }

  // List all log files in the directory
  if (existsSync(dir)) {
    const files = readdirSync(dir).filter((f) => f.startsWith("llm-doctor-") && f.endsWith(".jsonl"));
    if (files.length > 0) {
      console.log();
      console.log(`  Log files (${files.length}):`);
      for (const f of files.sort()) {
        const fp = join(dir, f);
        const st = statSync(fp);
        console.log(`    ${f}  ${formatBytes(st.size)}`);
      }
    }
  }
}

// ---------------------------------------------------------------------------
// openclaw doctor tail
// ---------------------------------------------------------------------------

function runTail(cfg: PluginConfig): void {
  const dir = resolveDir(cfg.outputDir);
  const logFile = currentLogPath(dir);

  if (!existsSync(logFile)) {
    console.log(`No log file for today: ${logFile}`);
    return;
  }

  const lines = readLines(logFile);
  const tailCount = 20;
  const start = Math.max(0, lines.length - tailCount);
  const tail = lines.slice(start);

  console.log(`Tail of ${logFile} (last ${tail.length} of ${lines.length} records):\n`);

  for (const line of tail) {
    try {
      const record = JSON.parse(line) as Record<string, unknown>;
      const ts = record.ts
        ? new Date(record.ts as number).toISOString().slice(11, 23)
        : "???";
      const type = (record.type as string) ?? "unknown";
      const session = (record.sessionId as string)?.slice(0, 8) ?? "-";
      const model = (record.model as string) ?? "";
      const provider = (record.provider as string) ?? "";
      const extra: string[] = [];

      if (model) extra.push(`model=${model}`);
      if (provider) extra.push(`provider=${provider}`);
      if (record.toolName) extra.push(`tool=${record.toolName}`);
      if (record.durationMs !== undefined) extra.push(`${record.durationMs}ms`);
      if (record.success !== undefined) extra.push(record.success ? "ok" : "FAIL");
      if (record.error) extra.push(`err=${record.error}`);

      const extraStr = extra.length > 0 ? `  ${extra.join(" ")}` : "";
      console.log(`  ${ts}  ${type.padEnd(20)} session=${session}${extraStr}`);
    } catch {
      // Unparseable line — print raw (truncated)
      console.log(`  ${line.slice(0, 120)}`);
    }
  }
}

// ---------------------------------------------------------------------------
// openclaw doctor stats
// ---------------------------------------------------------------------------

function runStats(cfg: PluginConfig): void {
  const dir = resolveDir(cfg.outputDir);
  const logFile = currentLogPath(dir);

  if (!existsSync(logFile)) {
    console.log(`No log file for today: ${logFile}`);
    return;
  }

  const lines = readLines(logFile);
  const typeCounts: Record<string, number> = {};
  const sessions = new Set<string>();
  const models = new Set<string>();
  let totalDurationMs = 0;
  let durationCount = 0;

  for (const line of lines) {
    try {
      const record = JSON.parse(line) as Record<string, unknown>;
      const type = (record.type as string) ?? "unknown";
      typeCounts[type] = (typeCounts[type] ?? 0) + 1;

      if (record.sessionId) sessions.add(record.sessionId as string);
      if (record.model) models.add(record.model as string);
      if (typeof record.durationMs === "number") {
        totalDurationMs += record.durationMs;
        durationCount++;
      }
    } catch {
      // skip unparseable lines
    }
  }

  console.log(`LLM Doctor Stats — ${todayDateStr()}\n`);
  console.log(`  Log file:       ${logFile}`);
  console.log(`  Total records:  ${lines.length}`);
  console.log(`  Sessions:       ${sessions.size}`);
  console.log(`  Models used:    ${models.size > 0 ? Array.from(models).join(", ") : "(none)"}`);
  console.log(
    `  Total duration: ${totalDurationMs > 0 ? `${(totalDurationMs / 1000).toFixed(1)}s (across ${durationCount} records)` : "(no duration data)"}`,
  );

  console.log();
  console.log("  Records by type:");

  const sortedTypes = Object.entries(typeCounts).sort((a, b) => b[1] - a[1]);
  for (const [type, count] of sortedTypes) {
    console.log(`    ${type.padEnd(24)} ${count}`);
  }
}

// ---------------------------------------------------------------------------
// CLI registration — called from plugin index.ts
// ---------------------------------------------------------------------------

export function registerDoctorCli(params: {
  program: any;
  cfg: PluginConfig;
}): void {
  const { program, cfg } = params;

  const root = program
    .command("doctor")
    .description("LLM Doctor diagnostic commands");

  root
    .command("status")
    .description("Show plugin status: output dir, capture settings, current log file")
    .action(() => {
      runStatus(cfg);
    });

  root
    .command("tail")
    .description("Live tail the current day's JSONL file (last 20 records)")
    .action(() => {
      runTail(cfg);
    });

  root
    .command("stats")
    .description("Quick stats: total records, records by type, sessions, models, duration")
    .action(() => {
      runStats(cfg);
    });
}
