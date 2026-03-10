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
// ---------------------------------------------------------------------------

export interface BaseRecord {
  type: string;
  ts: number;
  sessionKey?: string;
  agentId?: string;
  runId?: string;
}

export interface LlmInputRecord extends BaseRecord {
  type: "llm.input";
  channelId?: string;
  model?: string;
  provider?: string;
  isPrimary?: boolean;
  fallbackReason?: string;
  payload?: {
    system?: unknown;
    messages?: unknown[];
    tools?: unknown[];
    maxTokens?: number;
    temperature?: number;
    thinkingBudget?: number;
  };
}

export interface LlmOutputRecord extends BaseRecord {
  type: "llm.output";
  model?: string;
  provider?: string;
  success: boolean;
  error?: string;
  errorCode?: string;
  statusCode?: number;
  payload?: {
    content?: unknown[];
    thinking?: unknown[];
    stopReason?: string;
  };
  usage?: {
    inputTokens?: number;
    outputTokens?: number;
    cacheCreationTokens?: number;
    cacheReadTokens?: number;
    thinkingTokens?: number;
  };
  durationMs?: number;
}

export interface ToolStartRecord extends BaseRecord {
  type: "tool.start";
  toolName: string;
  params?: unknown;
}

export interface ToolEndRecord extends BaseRecord {
  type: "tool.end";
  toolName: string;
  durationMs?: number;
  success: boolean;
  error?: string;
}

export interface AgentStartRecord extends BaseRecord {
  type: "agent.start";
  promptLength?: number;
}

export interface AgentEndRecord extends BaseRecord {
  type: "agent.end";
  success: boolean;
  durationMs?: number;
  error?: string;
}

export interface DiagnosticUsageRecord extends BaseRecord {
  type: "diagnostic.usage";
  model?: string;
  provider?: string;
  contextLimit?: number;
  inputTokens?: number;
  outputTokens?: number;
  cacheCreationTokens?: number;
  cacheReadTokens?: number;
  costUsd?: number;
}

export type DoctorRecord =
  | LlmInputRecord
  | LlmOutputRecord
  | ToolStartRecord
  | ToolEndRecord
  | AgentStartRecord
  | AgentEndRecord
  | DiagnosticUsageRecord;
