import type { OpenClawPluginApi } from "openclaw/plugin-sdk";
import { onDiagnosticEvent } from "openclaw/plugin-sdk";
import { JsonlWriter } from "./src/writer.js";
import { DEFAULT_CONFIG } from "./src/types.js";
import type { PluginConfig } from "./src/types.js";

export default {
  id: "claw-llm-doctor",
  name: "LLM Doctor",
  description:
    "Diagnostic interceptor for LLM Provider calls — records all LLM interactions to JSONL",

  register(api: OpenClawPluginApi) {
    const cfg: PluginConfig = {
      ...DEFAULT_CONFIG,
      ...((api.pluginConfig ?? {}) as Partial<PluginConfig>),
    };
    const writer = new JsonlWriter(cfg);

    // -----------------------------------------------------------------
    // LLM input — fires when the full request is about to go to the LLM
    // -----------------------------------------------------------------
    api.on("llm_input", (evt: Record<string, unknown>, ctx: Record<string, unknown>) => {
      writer.write({
        type: "llm.input",
        ts: Date.now(),
        sessionKey: str(ctx.sessionKey),
        agentId: str(ctx.agentId),
        channelId: str(ctx.channelId),
        runId: str(ctx.runId),
        model: str(evt.model),
        provider: str(evt.provider),
        isPrimary: evt.isPrimary as boolean | undefined,
        fallbackReason: str(evt.fallbackReason),
        payload: cfg.capturePayloads
          ? {
              system: evt.system,
              messages: evt.messages as unknown[] | undefined,
              tools: evt.tools as unknown[] | undefined,
              maxTokens: num(evt.maxTokens),
              temperature: num(evt.temperature),
              thinkingBudget: num(evt.thinkingBudget),
            }
          : undefined,
      });
    });

    // -----------------------------------------------------------------
    // LLM output — fires when the LLM response is received
    // -----------------------------------------------------------------
    api.on("llm_output", (evt: Record<string, unknown>, ctx: Record<string, unknown>) => {
      const usage = evt.usage as Record<string, unknown> | undefined;
      writer.write({
        type: "llm.output",
        ts: Date.now(),
        sessionKey: str(ctx.sessionKey),
        agentId: str(ctx.agentId),
        runId: str(ctx.runId),
        model: str(evt.model),
        provider: str(evt.provider),
        success: !evt.error,
        error: str(evt.error),
        errorCode: str(evt.errorCode),
        statusCode: num(evt.statusCode),
        payload: cfg.capturePayloads
          ? {
              content: evt.content as unknown[] | undefined,
              thinking: evt.thinking as unknown[] | undefined,
              stopReason: str(evt.stopReason),
            }
          : undefined,
        usage: usage
          ? {
              inputTokens: num(usage.inputTokens),
              outputTokens: num(usage.outputTokens),
              cacheCreationTokens: num(usage.cacheCreationTokens),
              cacheReadTokens: num(usage.cacheReadTokens),
              thinkingTokens: num(usage.thinkingTokens),
            }
          : undefined,
        durationMs: num(evt.durationMs),
      });
    });

    // -----------------------------------------------------------------
    // Tool calls
    // -----------------------------------------------------------------
    api.on("before_tool_call", (evt: Record<string, unknown>, ctx: Record<string, unknown>) => {
      writer.write({
        type: "tool.start",
        ts: Date.now(),
        sessionKey: str(ctx.sessionKey),
        agentId: str(ctx.agentId),
        runId: str(ctx.runId),
        toolName: str(evt.toolName) ?? "unknown",
        params: cfg.capturePayloads ? evt.params : undefined,
      });
    });

    api.on("after_tool_call", (evt: Record<string, unknown>, ctx: Record<string, unknown>) => {
      writer.write({
        type: "tool.end",
        ts: Date.now(),
        sessionKey: str(ctx.sessionKey),
        agentId: str(ctx.agentId),
        runId: str(ctx.runId),
        toolName: str(evt.toolName) ?? "unknown",
        durationMs: num(evt.durationMs),
        success: !evt.error,
        error: str(evt.error),
      });
    });

    // -----------------------------------------------------------------
    // Agent lifecycle
    // -----------------------------------------------------------------
    api.on("before_agent_start", (evt: Record<string, unknown>, ctx: Record<string, unknown>) => {
      const prompt = evt.prompt;
      writer.write({
        type: "agent.start",
        ts: Date.now(),
        sessionKey: str(ctx.sessionKey),
        agentId: str(ctx.agentId),
        runId: str(ctx.runId),
        promptLength: typeof prompt === "string" ? prompt.length : undefined,
      });
    });

    api.on("agent_end", (evt: Record<string, unknown>, ctx: Record<string, unknown>) => {
      writer.write({
        type: "agent.end",
        ts: Date.now(),
        sessionKey: str(ctx.sessionKey),
        agentId: str(ctx.agentId),
        runId: str(ctx.runId),
        success: (evt.success as boolean) ?? true,
        durationMs: num(evt.durationMs),
        error: str(evt.error),
      });
    });

    // -----------------------------------------------------------------
    // Diagnostic: model.usage — token/cost metrics
    // -----------------------------------------------------------------
    const unsubscribe = onDiagnosticEvent((diag: Record<string, unknown>) => {
      if (diag.type !== "model.usage") return;
      writer.write({
        type: "diagnostic.usage",
        ts: Date.now(),
        sessionKey: str(diag.sessionKey),
        agentId: str(diag.agentId),
        runId: str(diag.runId),
        model: str(diag.model),
        provider: str(diag.provider),
        contextLimit: num(diag.contextLimit),
        inputTokens: num(diag.inputTokens),
        outputTokens: num(diag.outputTokens),
        cacheCreationTokens: num(diag.cacheCreationTokens),
        cacheReadTokens: num(diag.cacheReadTokens),
        costUsd: num(diag.costUsd),
      });
    });

    // Register a service so the Gateway can cleanly stop us
    api.registerService({
      id: "llm-doctor-writer",
      start() {},
      stop() {
        unsubscribe();
      },
    });
  },
};

// ---------------------------------------------------------------------------
// Helpers — safely extract typed values from untyped event payloads
// ---------------------------------------------------------------------------
function str(v: unknown): string | undefined {
  return typeof v === "string" ? v : undefined;
}

function num(v: unknown): number | undefined {
  return typeof v === "number" && Number.isFinite(v) ? v : undefined;
}
