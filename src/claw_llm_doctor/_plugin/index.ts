import type { OpenClawPluginApi } from "openclaw/plugin-sdk";
import { onDiagnosticEvent } from "openclaw/plugin-sdk";
import { JsonlWriter } from "./src/writer.js";
import { DEFAULT_CONFIG } from "./src/types.js";
import type { PluginConfig } from "./src/types.js";
import { registerDoctorCli } from "./src/cli.js";

const plugin = {
  id: "claw-llm-doctor",
  name: "LLM Doctor",
  description:
    "Diagnostic interceptor — records all LLM interactions to JSONL",

  register(api: OpenClawPluginApi) {
    const cfg: PluginConfig = {
      ...DEFAULT_CONFIG,
      ...((api.pluginConfig ?? {}) as Partial<PluginConfig>),
    };
    const writer = new JsonlWriter(cfg);

    api.logger.info(`llm-doctor: writing to ${cfg.outputDir}`);

    // Track llm_input timestamps for duration calculation in llm_output.
    // Key: "runId:sessionId" → timestamp
    // Entries are cleaned up on llm_output, plus a periodic sweep for
    // orphans (e.g. network failures where llm_output never fires).
    const inputTimestamps = new Map<string, number>();
    const INPUT_TS_MAX_AGE_MS = 10 * 60 * 1000; // 10 minutes
    let inputTsSweepTimer: ReturnType<typeof setInterval> | undefined;

    // -----------------------------------------------------------------
    // before_model_resolve — capture model routing decisions
    // -----------------------------------------------------------------
    api.on("before_model_resolve", (evt, ctx) => {
      writer.write({
        type: "model.resolve",
        ts: Date.now(),
        sessionKey: ctx.sessionKey,
        sessionId: ctx.sessionId,
        agentId: ctx.agentId,
        channelId: ctx.channelId,
        trigger: ctx.trigger,
        prompt: cfg.capturePayloads ? evt.prompt : undefined,
      });
      // Don't override model — we're just observing
      return undefined;
    });

    // -----------------------------------------------------------------
    // llm_input — fires when the full request is about to go to the LLM
    // -----------------------------------------------------------------
    api.on("llm_input", (evt, ctx) => {
      const now = Date.now();
      // Store timestamp for duration calculation in the paired llm_output
      const pairKey = `${evt.runId}:${ctx.sessionId}`;
      inputTimestamps.set(pairKey, now);

      writer.write({
        type: "llm.input",
        ts: now,
        sessionKey: ctx.sessionKey,
        sessionId: ctx.sessionId,
        agentId: ctx.agentId,
        runId: evt.runId,
        channelId: ctx.channelId,
        trigger: ctx.trigger,
        provider: evt.provider,
        model: evt.model,
        payload: cfg.capturePayloads
          ? {
              systemPrompt: evt.systemPrompt,
              prompt: evt.prompt,
              historyMessages: evt.historyMessages,
              imagesCount: evt.imagesCount,
            }
          : undefined,
      });
    });

    // -----------------------------------------------------------------
    // llm_output — fires when the LLM response is received
    // -----------------------------------------------------------------
    api.on("llm_output", (evt, ctx) => {
      // Infer success: the SDK doesn't provide an explicit success flag.
      // If lastAssistant has non-empty content, the call succeeded.
      // Note: empty arrays are truthy in JS, so we must check .length.
      const la = evt.lastAssistant as Record<string, unknown> | undefined;
      const laContent = Array.isArray(la?.content) ? la.content as unknown[] : undefined;
      const hasContent = (laContent && laContent.length > 0) || (evt.assistantTexts && evt.assistantTexts.length > 0);
      const stopReason = la?.stopReason as string | undefined;

      // Calculate duration from paired llm_input timestamp
      const pairKey = `${evt.runId}:${ctx.sessionId}`;
      const inputTs = inputTimestamps.get(pairKey);
      const now = Date.now();
      const durationMs = inputTs != null ? now - inputTs : undefined;
      if (inputTs != null) inputTimestamps.delete(pairKey);

      writer.write({
        type: "llm.output",
        ts: now,
        sessionKey: ctx.sessionKey,
        sessionId: ctx.sessionId,
        agentId: ctx.agentId,
        runId: evt.runId,
        channelId: ctx.channelId,
        trigger: ctx.trigger,
        provider: evt.provider,
        model: evt.model,
        success: !!hasContent,
        durationMs,
        stopReason,
        payload: cfg.capturePayloads
          ? {
              assistantTexts: evt.assistantTexts,
              lastAssistant: evt.lastAssistant,
            }
          : undefined,
        usage: evt.usage
          ? {
              input: evt.usage.input,
              output: evt.usage.output,
              cacheRead: evt.usage.cacheRead,
              cacheWrite: evt.usage.cacheWrite,
              total: evt.usage.total,
            }
          : undefined,
      });
    });

    // -----------------------------------------------------------------
    // Tool calls
    // -----------------------------------------------------------------
    api.on("before_tool_call", (evt, ctx) => {
      writer.write({
        type: "tool.start",
        ts: Date.now(),
        sessionKey: ctx.sessionKey,
        sessionId: ctx.sessionId,
        agentId: ctx.agentId,
        runId: ctx.runId ?? evt.runId,
        toolName: evt.toolName,
        toolCallId: evt.toolCallId,
        params: cfg.capturePayloads ? evt.params : undefined,
      });
      return undefined;
    });

    api.on("after_tool_call", (evt, ctx) => {
      writer.write({
        type: "tool.end",
        ts: Date.now(),
        sessionKey: ctx.sessionKey,
        sessionId: ctx.sessionId,
        agentId: ctx.agentId,
        runId: ctx.runId ?? evt.runId,
        toolName: evt.toolName,
        toolCallId: evt.toolCallId,
        durationMs: evt.durationMs,
        success: !evt.error,
        error: evt.error,
      });
    });

    // -----------------------------------------------------------------
    // Agent lifecycle
    // -----------------------------------------------------------------
    api.on("before_agent_start", (evt, ctx) => {
      writer.write({
        type: "agent.start",
        ts: Date.now(),
        sessionKey: ctx.sessionKey,
        sessionId: ctx.sessionId,
        agentId: ctx.agentId,
        channelId: ctx.channelId,
        trigger: ctx.trigger,
        prompt: cfg.capturePayloads ? evt.prompt : undefined,
        messageCount: evt.messages?.length,
      });
      return undefined;
    });

    api.on("agent_end", (evt, ctx) => {
      writer.write({
        type: "agent.end",
        ts: Date.now(),
        sessionKey: ctx.sessionKey,
        sessionId: ctx.sessionId,
        agentId: ctx.agentId,
        channelId: ctx.channelId,
        trigger: ctx.trigger,
        success: evt.success,
        durationMs: evt.durationMs,
        error: evt.error,
        messageCount: evt.messages?.length,
      });
    });

    // -----------------------------------------------------------------
    // Compaction events
    // -----------------------------------------------------------------
    api.on("before_compaction", (evt, ctx) => {
      writer.write({
        type: "compaction.before",
        ts: Date.now(),
        sessionKey: ctx.sessionKey,
        sessionId: ctx.sessionId,
        agentId: ctx.agentId,
        messageCount: evt.messageCount,
        compactingCount: evt.compactingCount,
        tokenCount: evt.tokenCount,
        sessionFile: evt.sessionFile,
      });
    });

    api.on("after_compaction", (evt, ctx) => {
      writer.write({
        type: "compaction.after",
        ts: Date.now(),
        sessionKey: ctx.sessionKey,
        sessionId: ctx.sessionId,
        agentId: ctx.agentId,
        messageCount: evt.messageCount,
        compactedCount: evt.compactedCount,
        tokenCount: evt.tokenCount,
        sessionFile: evt.sessionFile,
      });
    });

    // -----------------------------------------------------------------
    // Diagnostic: model.usage — token/cost metrics from the runtime
    // -----------------------------------------------------------------
    const unsubDiag = onDiagnosticEvent((diag) => {
      if (diag.type !== "model.usage") return;
      const evt = diag as Record<string, unknown>;
      const usage = (evt.usage ?? {}) as Record<string, unknown>;
      const context = (evt.context ?? {}) as Record<string, unknown>;
      writer.write({
        type: "diagnostic.usage",
        ts: Date.now(),
        sessionKey: evt.sessionKey as string | undefined,
        sessionId: evt.sessionId as string | undefined,
        model: evt.model as string | undefined,
        provider: evt.provider as string | undefined,
        channel: evt.channel as string | undefined,
        contextLimit: context.limit as number | undefined,
        contextUsed: context.used as number | undefined,
        inputTokens: usage.input as number | undefined,
        outputTokens: usage.output as number | undefined,
        cacheReadTokens: usage.cacheRead as number | undefined,
        cacheWriteTokens: usage.cacheWrite as number | undefined,
        totalTokens: usage.total as number | undefined,
        costUsd: evt.costUsd as number | undefined,
        durationMs: evt.durationMs as number | undefined,
      });
    });

    // -----------------------------------------------------------------
    // Service lifecycle — clean shutdown
    // -----------------------------------------------------------------
    api.registerService({
      id: "llm-doctor-writer",
      start() {
        // Sweep orphaned inputTimestamps every 5 minutes
        inputTsSweepTimer = setInterval(() => {
          const cutoff = Date.now() - INPUT_TS_MAX_AGE_MS;
          for (const [key, ts] of inputTimestamps) {
            if (ts < cutoff) inputTimestamps.delete(key);
          }
        }, 5 * 60 * 1000);
        api.logger.info("llm-doctor: service started");
      },
      async stop() {
        if (inputTsSweepTimer) clearInterval(inputTsSweepTimer);
        inputTimestamps.clear();
        unsubDiag();
        await writer.close();
        api.logger.info("llm-doctor: service stopped");
      },
    });

    // -----------------------------------------------------------------
    // CLI — `openclaw llm-doctor status|tail|stats`
    // -----------------------------------------------------------------
    api.registerCli(
      ({ program }) => registerDoctorCli({ program, cfg }),
      { commands: ["llm-doctor"] },
    );
  },
};

export default plugin;
