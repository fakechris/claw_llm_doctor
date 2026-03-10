# claw_llm_doctor - Implementation Plan

## 1. Project Overview

claw_llm_doctor is a diagnostic tool for OpenClaw that intercepts, records, and analyzes
all LLM Provider calls. It combines:
- **Data collection** (plugin-based interception, similar to opik-openclaw / knostic/openclaw-telemetry)
- **Context analysis** (similar to context-lens / context-doctor)
- **Diagnostic reporting** (custom analysis for system prompt ordering, thinking process, compression)

## 2. Landscape Analysis

### 2.1 Existing Projects

| Project | Type | Strengths | Gaps (for our use case) |
|---------|------|-----------|-------------------------|
| [opik-openclaw](https://github.com/comet-ml/opik-openclaw) | OpenClaw Plugin | Full trace capture, LLM/tool/subagent spans, token & cost tracking | Data goes to Opik cloud; no local context composition analysis; no system prompt ordering analysis |
| [knostic/openclaw-telemetry](https://github.com/knostic/openclaw-telemetry) | OpenClaw Plugin | JSONL logging, redaction, hash chains, SIEM forwarding | No LLM input/output capture (only tool calls & messages); no analysis layer |
| [context-lens](https://github.com/larsderidder/context-lens) | Transparent Proxy | Framework-agnostic; breaks down system prompts vs tools vs history vs thinking blocks; health scoring | External proxy (not an OpenClaw plugin); no Primary/Fallback tracking; no system prompt ordering analysis |
| [context-doctor](https://github.com/jzOcb/context-doctor) | OpenClaw Skill | Token budget visualization; workspace file truncation detection; health scoring | Static analysis only (no runtime interception); no LLM I/O capture; no thinking process analysis |
| [ClawMetry](https://github.com/vivekchand/clawmetry) | Dashboard | Real-time dashboard; token costs; session tracking | Visualization only; no deep content analysis; no raw payload preservation |
| [henrikrexed/openclaw-observability-plugin](https://github.com/henrikrexed/openclaw-observability-plugin) | OpenClaw Plugin | OTel-based; agent lifecycle capture | Cannot trace individual LLM calls due to ESM/CJS module isolation |
| Built-in Diagnostic-OTel | OpenClaw Built-in | OTel traces/metrics/logs; token usage, cost, context size | Generic metrics; no raw payload capture; no content-level analysis |

### 2.2 The Gap

No existing tool provides **all** of the following in one package:
1. Runtime interception of LLM calls **as an OpenClaw plugin** (not external proxy)
2. Complete raw payload preservation (input messages + output responses)
3. Primary/Fallback routing decision tracking with error classification
4. Deep content analysis: system prompt ordering, compression detection, thinking process separation

**claw_llm_doctor fills this gap.**

## 3. Architecture

```
+---------------------------+
|     OpenClaw Gateway      |
|  +---------------------+  |
|  | claw_llm_doctor      |  |     +-----------------+
|  | (Plugin)             |  |     | Analysis Engine  |
|  |                      |  |     | (CLI / Server)   |
|  | - llm_input hook  ---|--|---->| - Context Analyzer|
|  | - llm_output hook ---|--|---->| - Prompt Analyzer |
|  | - diagnostic events -|--|---->| - Think Analyzer  |
|  | - tool hooks      ---|--|---->| - Report Generator|
|  +---------------------+  |     +-----------------+
|                           |              |
+---------------------------+              v
                                  +------------------+
                                  |  JSONL Log Files  |
                                  |  (Raw Payloads)   |
                                  +------------------+
                                           |
                                           v
                                  +------------------+
                                  |  Diagnostic       |
                                  |  Reports          |
                                  |  (Terminal / HTML) |
                                  +------------------+
```

### 3.1 Two-Component Design

**Component A: OpenClaw Plugin (TypeScript)**
- Runs inside the Gateway process
- Hooks into `llm_input`, `llm_output`, `before_tool_call`, `after_tool_call`,
  `before_agent_start`, `agent_end`, and `model.usage` diagnostics
- Writes structured JSONL log files with complete payloads
- Lightweight; fire-and-forget async writes

**Component B: Analysis Engine (Python)**
- Reads JSONL log files produced by the plugin
- Performs deep analysis on captured data
- Generates diagnostic reports
- Can run as CLI tool or optional web server

### 3.2 Why Two Languages?
- **Plugin must be TypeScript** (OpenClaw plugins are TS modules loaded via jiti)
- **Analysis benefits from Python** (rich ecosystem: tiktoken for token counting,
  visualization libraries, easier scripting for ad-hoc analysis)

## 4. Detailed Design

### 4.1 Component A: OpenClaw Plugin

#### 4.1.1 Plugin Manifest (`openclaw.plugin.json`)

```json
{
  "id": "claw-llm-doctor",
  "name": "LLM Doctor",
  "description": "Diagnostic interceptor for LLM Provider calls - records and analyzes all LLM interactions",
  "configSchema": {
    "type": "object",
    "properties": {
      "outputDir": {
        "type": "string",
        "description": "Directory for JSONL log files",
        "default": "~/.openclaw/logs/llm-doctor"
      },
      "capturePayloads": {
        "type": "boolean",
        "description": "Whether to capture full request/response payloads",
        "default": true
      },
      "redactSecrets": {
        "type": "boolean",
        "description": "Redact API keys and tokens from captured payloads",
        "default": true
      },
      "maxPayloadSize": {
        "type": "number",
        "description": "Maximum payload size to capture (bytes, 0 = unlimited)",
        "default": 0
      },
      "rotateMaxSize": {
        "type": "number",
        "description": "Log rotation: max file size in bytes",
        "default": 104857600
      }
    }
  }
}
```

#### 4.1.2 Event Capture Strategy

**Event: `llm_input`** (Available since v2026.2.15, parity fixed in v2026.3.2)
```typescript
api.on("llm_input", (evt, ctx) => {
  writer.write({
    type: "llm.input",
    ts: Date.now(),
    sessionKey: ctx.sessionKey,
    agentId: ctx.agentId,
    channelId: ctx.channelId,
    runId: ctx.runId,
    // Model routing info
    model: evt.model,           // resolved model id (e.g. "anthropic/claude-sonnet-4-6")
    provider: evt.provider,     // provider name
    isPrimary: evt.isPrimary,   // true if primary model, false if fallback
    fallbackReason: evt.fallbackReason, // why primary was skipped (if applicable)
    // Complete request payload
    payload: {
      messages: evt.messages,   // full message array including system prompts
      tools: evt.tools,         // tool definitions
      maxTokens: evt.maxTokens,
      temperature: evt.temperature,
      thinkingBudget: evt.thinkingBudget,
    },
  });
});
```

**Event: `llm_output`**
```typescript
api.on("llm_output", (evt, ctx) => {
  writer.write({
    type: "llm.output",
    ts: Date.now(),
    sessionKey: ctx.sessionKey,
    agentId: ctx.agentId,
    runId: ctx.runId,
    model: evt.model,
    provider: evt.provider,
    // Response data
    success: !evt.error,
    error: evt.error,
    errorCode: evt.errorCode,      // e.g. "auth_failed", "rate_limited", "timeout"
    statusCode: evt.statusCode,
    // Complete response payload
    payload: {
      content: evt.content,         // assistant response content blocks
      thinking: evt.thinking,       // thinking blocks (if extended thinking enabled)
      stopReason: evt.stopReason,
    },
    // Usage metrics
    usage: {
      inputTokens: evt.usage?.inputTokens,
      outputTokens: evt.usage?.outputTokens,
      cacheCreationTokens: evt.usage?.cacheCreationTokens,
      cacheReadTokens: evt.usage?.cacheReadTokens,
      thinkingTokens: evt.usage?.thinkingTokens,
    },
    durationMs: evt.durationMs,
  });
});
```

**Event: `model.usage` Diagnostic**
```typescript
onDiagnosticEvent((diag) => {
  if (diag.type === "model.usage") {
    writer.write({
      type: "diagnostic.usage",
      ts: Date.now(),
      sessionKey: diag.sessionKey,
      model: diag.model,
      provider: diag.provider,
      contextLimit: diag.contextLimit,
      inputTokens: diag.inputTokens,
      outputTokens: diag.outputTokens,
      costUsd: diag.costUsd,
    });
  }
});
```

**Additional hooks: tool calls, agent lifecycle** (similar to knostic/openclaw-telemetry pattern)

#### 4.1.3 JSONL Writer

Features:
- Async non-blocking writes (fire-and-forget with buffer)
- File rotation by size (configurable, default 100MB)
- Secret redaction (API keys, bearer tokens) using configurable regex
- One file per day: `llm-doctor-YYYY-MM-DD.jsonl`

#### 4.1.4 CLI Commands

Register under `openclaw doctor` namespace:
- `openclaw doctor status` - Show plugin status and log file location
- `openclaw doctor tail` - Live tail of captured events
- `openclaw doctor export --session <key>` - Export a session's data

### 4.2 Component B: Analysis Engine (Python)

#### 4.2.1 Module Structure

```
analysis/
  __init__.py
  cli.py                  # CLI entry point
  loader.py               # JSONL log file loader & session grouper
  analyzers/
    __init__.py
    routing.py            # Layer 1: LM routing analysis
    context.py            # Layer 3a: context length analysis
    prompt_order.py       # Layer 3b: system prompt ordering analysis
    prompt_compression.py # Layer 3c: system prompt compression analysis
    thinking.py           # Layer 3d: thinking process analysis
  reporters/
    __init__.py
    terminal.py           # Terminal report output
    html.py               # HTML report output
    json_report.py        # JSON report output
  utils/
    tokens.py             # Token counting (tiktoken / char estimation)
    diff.py               # Text diff utilities for compression detection
```

#### 4.2.2 Layer 1: LM Routing Analysis (`routing.py`)

**Goal**: Track all LM scheduling, analyze Primary vs Fallback success rates, classify errors.

**Inputs**: `llm.input` + `llm.output` + `diagnostic.usage` events

**Analysis**:

```
1(a) Primary/Fallback Mechanism:
  - For each LLM call, identify: was Primary or Fallback used?
  - Build a timeline: Primary -> (fail) -> Fallback -> (success/fail)
  - Detect cascading fallback chains

1(b) Success Rate Analysis:
  - Per-session and aggregate success rates
  - Success rate by model, by provider
  - Success rate over time (detect degradation patterns)
  - User request -> LLM call fan-out ratio

1(c) Error Classification:
  - auth_failed: API Key issues (expired, invalid, wrong provider)
  - rate_limited: Rate limit exceeded
  - timeout: Model didn't respond in time
  - context_length_exceeded: Input too large
  - server_error: Provider 5xx errors
  - unknown: Unclassified errors
  - Error frequency and patterns over time
```

**Output**: Routing diagnostic report with:
- Summary table: total calls, primary success %, fallback trigger %, fallback success %
- Error breakdown table with counts and example messages
- Timeline visualization of routing decisions

#### 4.2.3 Layer 2: Raw Payload Preservation

**Goal**: Complete preservation of LLM input/output for deep analysis.

This is handled by the plugin's JSONL writer. The analysis engine provides:
- `loader.py`: Parse JSONL files, group by session/agent/run
- Session replay: reconstruct full conversation from captured events
- Export to standard formats (HAR-like, context-lens LHAR)

#### 4.2.4 Layer 3a: Context Length Analysis (`context.py`)

**Goal**: Analyze message length and context window utilization.

**Analysis**:
```
- Per-turn context composition breakdown:
  - System prompt tokens (total and per-section)
  - Tool definition tokens
  - Conversation history tokens
  - Tool result tokens
  - Thinking block tokens (if returned from previous turns)
  - Image tokens

- Context utilization ratio: used_tokens / context_limit
  - Health score (green/yellow/red, similar to context-doctor)

- Context growth curve over session lifetime
  - Detect when compaction occurred (sudden drop in context size)
  - Estimate context remaining for each turn

- Large payload detection:
  - Tool results exceeding threshold
  - Unusually large system prompts
  - Bloated tool definitions
```

#### 4.2.5 Layer 3b: System Prompt Ordering Analysis (`prompt_order.py`)

**Goal**: Analyze the embedding order of system prompt sections.

OpenClaw constructs the system prompt from multiple sources:
1. Core system prompt (model instructions, safety guidelines)
2. Workspace bootstrap files (AGENTS.md, MEMORY.md, etc.)
3. Skill definitions and tool schemas
4. Session-specific context (memory, prior compact summaries)

**Analysis**:
```
- Identify and label each system prompt section by source:
  - [CORE] Built-in OpenClaw system prompt
  - [WORKSPACE] From bootstrap/workspace files
  - [SKILL] From installed skills
  - [MEMORY] From memory/session context
  - [COMPACT] From compaction summaries

- Track ordering across turns:
  - Does the order remain consistent?
  - Does any section get displaced after compaction?

- Section boundary detection using known markers/delimiters

- Cross-session comparison:
  - Are the same sections always in the same order?
  - Does ordering differ between Primary and Fallback models?
```

#### 4.2.6 Layer 3c: System Prompt Compression Analysis (`prompt_compression.py`)

**Goal**: Detect whether system prompt content is lost due to truncation or compaction.

**Analysis**:
```
- Baseline capture:
  - Record the full system prompt from the first turn of a session (before any compression)
  - This serves as the "ground truth"

- Per-turn diff:
  - Compare current system prompt against baseline
  - Detect: identical / truncated / compacted / missing sections

- Truncation detection (matches OpenClaw's 70/20/10 split):
  - Look for truncation markers in system prompt content
  - Identify which workspace files were truncated
  - Calculate: original size vs truncated size vs character budget

- Content loss scoring:
  - Semantic similarity between original and current system prompt
  - Identify specific sections/instructions that were lost
  - Flag critical content loss (e.g., safety guidelines, key instructions)

- Compaction analysis:
  - Before/after comparison when /compact is detected
  - What information was preserved vs summarized vs lost
  - Key entity preservation check (file paths, IDs, function names)
```

#### 4.2.7 Layer 3d: Thinking Process Analysis (`thinking.py`)

**Goal**: Analyze the model's thinking process for cleanliness and separation.

**Analysis**:
```
- Thinking block extraction:
  - Identify thinking blocks in the response
  - Verify they are properly tagged/separated from content blocks

- Separation cleanliness:
  - Check: does the final response content contain thinking artifacts?
    (e.g., "Let me think about...", "I need to consider...", reasoning steps)
  - Detect leaked thinking patterns in non-thinking content blocks
  - Pattern matching for common thinking leakage indicators

- Thinking quality metrics:
  - Thinking token ratio: thinking_tokens / total_output_tokens
  - Thinking coherence: does thinking logically lead to the response?
  - Thinking completeness: was thinking truncated (hit budget)?

- Cross-turn thinking consistency:
  - Does the model contradict its own thinking in subsequent turns?
  - Track thinking themes and decision points across a session

- Thinking content classification:
  - Planning / reasoning / self-correction / tool selection / code review
  - Distribution of thinking categories per session
```

## 5. Implementation Phases

### Phase 1: Plugin Core (TypeScript)
**Files to create:**
```
plugin/
  openclaw.plugin.json
  index.ts               # Plugin entry point
  package.json
  tsconfig.json
  src/
    writer.ts            # JSONL async writer with rotation
    redact.ts            # Secret redaction
    types.ts             # Event type definitions
```

**Deliverable**: A working OpenClaw plugin that captures all LLM events to JSONL.

**Validation**: Install the plugin, run an OpenClaw session, verify JSONL output contains
complete llm.input and llm.output records.

### Phase 2: Analysis Foundation (Python)
**Files to create:**
```
analysis/
  pyproject.toml
  cli.py
  loader.py
  utils/tokens.py
  analyzers/routing.py
  reporters/terminal.py
```

**Deliverable**: CLI tool that loads JSONL files and produces Layer 1 routing analysis.

**Validation**: Run `claw-doctor analyze --routing session.jsonl` and get a routing report.

### Phase 3: Context & Prompt Analysis
**Files to create:**
```
analysis/analyzers/
  context.py
  prompt_order.py
  prompt_compression.py
```

**Deliverable**: Context composition breakdown, prompt ordering, and compression detection.

### Phase 4: Thinking Process Analysis
**Files to create:**
```
analysis/analyzers/
  thinking.py
```

**Deliverable**: Thinking block analysis with leakage detection.

### Phase 5: Reporting & Polish
**Files to create:**
```
analysis/reporters/
  html.py
  json_report.py
```

**Deliverable**: Rich HTML reports with visualizations, JSON export for programmatic use.

## 6. Dependencies

### Plugin (TypeScript)
- `openclaw/plugin-sdk` (peer dependency, provided by OpenClaw)
- No other external dependencies (keep the plugin lightweight)

### Analysis Engine (Python)
- `tiktoken` - Token counting for OpenAI models
- `anthropic` - Token counting for Claude models (via API)
- `rich` - Terminal reporting
- `click` - CLI framework
- `jinja2` - HTML report templating
- `difflib` (stdlib) - Text diffing for compression analysis
- `orjson` - Fast JSON parsing for JSONL files

## 7. Configuration

### Plugin Config (via `~/.openclaw/config.json`)

```json
{
  "plugins": {
    "entries": {
      "claw-llm-doctor": {
        "enabled": true,
        "settings": {
          "outputDir": "~/.openclaw/logs/llm-doctor",
          "capturePayloads": true,
          "redactSecrets": true,
          "maxPayloadSize": 0,
          "rotateMaxSize": 104857600
        }
      }
    }
  }
}
```

### Analysis Config (via `~/.claw-doctor/config.toml`)

```toml
[general]
log_dir = "~/.openclaw/logs/llm-doctor"
default_format = "terminal"

[analysis]
token_estimator = "tiktoken"  # or "char" for fast estimation
thinking_leak_patterns = "default"  # or path to custom patterns file

[thresholds]
context_health_warning = 0.80   # yellow at 80% context used
context_health_critical = 0.95  # red at 95% context used
large_tool_result_tokens = 5000
```

## 8. JSONL Record Schema

### Common Fields
```json
{
  "type": "llm.input | llm.output | tool.start | tool.end | agent.start | agent.end | diagnostic.usage",
  "ts": 1710000000000,
  "sessionKey": "abc-123",
  "agentId": "agent-456",
  "runId": "run-789"
}
```

### llm.input Record (actual SDK shape)
```json
{
  "type": "llm.input",
  "ts": 1773132296972,
  "sessionKey": "agent:main:main",
  "sessionId": "a4fd48e3-...",
  "agentId": "main",
  "runId": "418052d6-...",
  "channelId": "feishu",
  "trigger": "user",
  "provider": "ark",
  "model": "doubao-seed-2.0-code",
  "payload": {
    "systemPrompt": "You are a personal assistant...",
    "prompt": "[Tue 2026-03-10 16:44 GMT+8] Say hello.",
    "historyMessages": [{"role": "user", "content": [...], "timestamp": ...}, ...],
    "imagesCount": 0
  }
}
```

### llm.output Record (actual SDK shape)
```json
{
  "type": "llm.output",
  "ts": 1773132343995,
  "sessionKey": "agent:main:main",
  "sessionId": "a4fd48e3-...",
  "agentId": "main",
  "runId": "418052d6-...",
  "provider": "ark",
  "model": "doubao-seed-2.0-code",
  "payload": {
    "assistantTexts": ["Hello! 👋"],
    "lastAssistant": {
      "role": "assistant",
      "content": [{"type": "text", "text": "Hello! 👋"}],
      "usage": {"input": 100412, "output": 5, "cacheRead": 3384, "cacheWrite": 0, "totalTokens": 103801,
                "cost": {"input": 0.200824, "output": 0.00004, "cacheRead": 0.001692, "total": 0.202556}},
      "stopReason": "stop"
    }
  },
  "usage": {
    "input": 100412,
    "output": 5,
    "cacheRead": 3384,
    "cacheWrite": 0,
    "total": 103801
  }
}
```

> **Note**: The SDK does not expose `isPrimary`, `fallbackReason`, `errorCode`, `statusCode`,
> `maxTokens`, `temperature`, `thinkingBudget`, or separate `thinking` blocks at the plugin
> hook level. Routing is inferred; thinking analysis uses `lastAssistant.content` blocks.

## 9. Key Decisions & Trade-offs

| Decision | Rationale |
|----------|-----------|
| Plugin (not proxy) | Direct access to OpenClaw internal state (routing decisions, model config, session context); no env var hacks needed |
| JSONL (not SQLite) | Simpler, streamable, easy to query with jq, compatible with existing tools; can always import to DB later |
| Two languages (TS + Python) | Plugin must be TS; analysis benefits from Python ecosystem; JSONL is the clean interface between them |
| Capture full payloads by default | Storage is cheap; having the data is invaluable for debugging; redaction handles secrets |
| Python CLI (not web dashboard) | ClawMetry already provides dashboards; our value is in deep analysis, not real-time monitoring |

## 10. Resolved Questions (formerly Open Questions)

1. **llm_input/llm_output payload completeness**: ✅ RESOLVED
   Verified against OpenClaw v2026.3.2 SDK types (`PluginHookLlmInputEvent`, `PluginHookLlmOutputEvent`).
   - `llm_input` provides: `runId`, `sessionId`, `provider`, `model`, `systemPrompt` (string),
     `prompt` (string), `historyMessages` (message array), `imagesCount` (number)
   - `llm_output` provides: `runId`, `sessionId`, `provider`, `model`, `assistantTexts` (string[]),
     `lastAssistant` (full message with content blocks + usage), `usage` (`{ input, output, cacheRead, cacheWrite, total }`)
   - Context (`PluginHookAgentContext`): `agentId`, `sessionKey`, `sessionId`, `channelId`, `trigger`, `runId`

2. **Primary/Fallback signal**: ✅ RESOLVED
   The SDK does NOT expose `isPrimary` or `fallbackReason` fields. Routing is inferred by comparing
   the model used in each call against `agents.defaults.model.primary` from the OpenClaw config.
   The analysis engine's `--primary-model` flag or auto-detection from `~/.openclaw/openclaw.json`
   handles this.

3. **System prompt structure**: ✅ RESOLVED
   The system prompt is delivered as a single string via `evt.systemPrompt`. It contains
   concatenated sections (CORE, WORKSPACE, TOOL, MEMORY, etc.) with markdown headers as delimiters.
   The `prompt_order` analyzer uses regex patterns to detect section boundaries.

4. **ContextEngine plugin (v2026.3.7)**: ⏳ DEFERRED
   Not yet tested with the new pluggable ContextEngine. The current implementation should be
   compatible since it reads the assembled system prompt, not the assembly process itself.

## 11. References

### Primary References
- [opik-openclaw](https://github.com/comet-ml/opik-openclaw) - Plugin pattern, LLM span tracking
- [context-doctor](https://github.com/jzOcb/context-doctor) - Context window health analysis
- [context-lens](https://github.com/larsderidder/context-lens) - Context composition breakdown, thinking block analysis
- [knostic/openclaw-telemetry](https://github.com/knostic/openclaw-telemetry) - JSONL logging, redaction, rotation

### Additional References
- [ClawMetry](https://github.com/vivekchand/clawmetry) - Real-time observability dashboard
- [henrikrexed/openclaw-observability-plugin](https://github.com/henrikrexed/openclaw-observability-plugin) - OTel plugin
- [OpenClaw Hooks Docs](https://openclaw-ai.com/en/docs/automation/hooks) - Hook system documentation
- [OpenClaw Discussion #20575](https://github.com/openclaw/openclaw/discussions/20575) - Hook bridge proposal
- [OpenClaw Discussion #8902](https://github.com/openclaw/openclaw/discussions/8902) - LLM tracing plugin proposal
- [OpenClaw Context Docs](https://docs.openclaw.ai/concepts/context) - Context management
- [LiteLLM](https://github.com/BerriAI/litellm) - LLM proxy with logging
- [Langfuse](https://langfuse.com/docs/observability/overview) - Open source LLM observability
- [OpenLLMetry](https://github.com/traceloop/openllmetry) - OTel-based LLM observability
