// ---------------------------------------------------------------------------
// Plugin configuration
// ---------------------------------------------------------------------------

export interface PluginConfig {
  outputDir: string;
  capturePayloads: boolean;
  redactSecrets: boolean;
  maxPayloadSize: number;
  rotateMaxSize: number;
}

export const DEFAULT_CONFIG: PluginConfig = {
  outputDir: "~/.openclaw/logs/llm-doctor",
  capturePayloads: true,
  redactSecrets: true,
  maxPayloadSize: 0,
  rotateMaxSize: 104_857_600, // 100 MB
};

// ---------------------------------------------------------------------------
// JSONL record types — written to disk by the plugin
//
// Field names align with the actual OpenClaw Plugin SDK hook payloads
// (PluginHookLlmInputEvent, PluginHookLlmOutputEvent, etc.)
// ---------------------------------------------------------------------------

export interface BaseRecord {
  type: string;
  ts: number;
  sessionKey?: string;
  sessionId?: string;
  agentId?: string;
  runId?: string;
  channelId?: string;
  trigger?: string;
}

export interface LlmInputRecord extends BaseRecord {
  type: "llm.input";
  provider?: string;
  model?: string;
  payload?: {
    systemPrompt?: string;
    prompt?: string;
    historyMessages?: unknown[];
    imagesCount?: number;
  };
}

export interface LlmOutputRecord extends BaseRecord {
  type: "llm.output";
  provider?: string;
  model?: string;
  payload?: {
    assistantTexts?: string[];
    lastAssistant?: unknown;
  };
  usage?: {
    input?: number;
    output?: number;
    cacheRead?: number;
    cacheWrite?: number;
    total?: number;
  };
}

export interface ModelResolveRecord extends BaseRecord {
  type: "model.resolve";
  prompt?: string;
  modelOverride?: string;
  providerOverride?: string;
}

export interface ToolStartRecord extends BaseRecord {
  type: "tool.start";
  toolName: string;
  toolCallId?: string;
  params?: unknown;
}

export interface ToolEndRecord extends BaseRecord {
  type: "tool.end";
  toolName: string;
  toolCallId?: string;
  durationMs?: number;
  success: boolean;
  error?: string;
}

export interface AgentStartRecord extends BaseRecord {
  type: "agent.start";
  prompt?: string;
  messageCount?: number;
}

export interface AgentEndRecord extends BaseRecord {
  type: "agent.end";
  success: boolean;
  durationMs?: number;
  error?: string;
  messageCount?: number;
}

export interface CompactionRecord extends BaseRecord {
  type: "compaction.before" | "compaction.after";
  messageCount?: number;
  compactingCount?: number;
  compactedCount?: number;
  tokenCount?: number;
  sessionFile?: string;
}

export interface DiagnosticUsageRecord extends BaseRecord {
  type: "diagnostic.usage";
  model?: string;
  provider?: string;
  channel?: string;
  contextLimit?: number;
  contextUsed?: number;
  inputTokens?: number;
  outputTokens?: number;
  cacheReadTokens?: number;
  cacheWriteTokens?: number;
  totalTokens?: number;
  costUsd?: number;
  durationMs?: number;
}

export type DoctorRecord =
  | LlmInputRecord
  | LlmOutputRecord
  | ModelResolveRecord
  | ToolStartRecord
  | ToolEndRecord
  | AgentStartRecord
  | AgentEndRecord
  | CompactionRecord
  | DiagnosticUsageRecord;
