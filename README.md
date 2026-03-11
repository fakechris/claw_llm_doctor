# claw_llm_doctor

Diagnostic tool for OpenClaw that intercepts, records, and analyzes all LLM Provider calls.

## What it does

- **Intercepts** every LLM request/response via an OpenClaw Gateway plugin
- **Records** complete payloads to JSONL with automatic rotation and secret redaction
- **Analyzes** routing decisions, context composition, system prompt integrity, and thinking process quality

## Components

| Component | Language | Purpose |
|-----------|----------|---------|
| `plugin/` | TypeScript | OpenClaw Gateway plugin — captures events to JSONL |
| `analysis/` | Python | CLI analysis engine — reads JSONL and generates reports |

---

## Plugin Installation

### Prerequisites

- OpenClaw >= 2026.3.2
- Node.js >= 22.12.0

### Install from local directory

```bash
# Clone this repo
git clone https://github.com/fakechris/claw_llm_doctor.git
cd claw_llm_doctor/plugin

# Copy to extensions and install dependencies
cp -r . ~/.openclaw/extensions/claw-llm-doctor
cd ~/.openclaw/extensions/claw-llm-doctor
npm install
```

### Development setup

```bash
# For active development, copy and install deps, then sync changes as needed
cp -r plugin ~/.openclaw/extensions/claw-llm-doctor
cd ~/.openclaw/extensions/claw-llm-doctor && npm install

# After making changes in plugin/, sync to extensions (preserves node_modules)
rsync -av --exclude node_modules --exclude package-lock.json plugin/ ~/.openclaw/extensions/claw-llm-doctor/
```

> **Note**: A plain symlink won't work because `npm install` is needed in the
> extensions directory to resolve the `openclaw` peer dependency.

### Configure

Add to `~/.openclaw/openclaw.json`:

```json
{
  "plugins": {
    "allow": ["claw-llm-doctor"],
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

### Restart Gateway

```bash
openclaw daemon restart
```

The plugin writes logs to `~/.openclaw/logs/llm-doctor/llm-doctor-YYYY-MM-DD.jsonl`.
Verify the plugin loaded:

```bash
openclaw plugins list        # should show LLM Doctor as "loaded"
openclaw plugins info claw-llm-doctor
```

### Verify

```bash
# Check logs are being written
ls ~/.openclaw/logs/llm-doctor/

# Quick status via the plugin CLI
openclaw llm-doctor status

# Tail live events
tail -f ~/.openclaw/logs/llm-doctor/llm-doctor-$(date +%Y-%m-%d).jsonl | jq .
```

### Plugin CLI Commands

The plugin registers commands under `openclaw llm-doctor`:

```bash
openclaw llm-doctor status   # Output dir, capture settings, log file size, record count
openclaw llm-doctor tail     # Last 20 records from today's log
openclaw llm-doctor stats    # Records by type, sessions, models, total duration
```

### Plugin Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `outputDir` | string | `~/.openclaw/logs/llm-doctor` | JSONL output directory |
| `capturePayloads` | boolean | `true` | Capture full request/response payloads |
| `redactSecrets` | boolean | `true` | Redact API keys and tokens |
| `maxPayloadSize` | number | `0` | Max payload size in bytes (0 = unlimited) |
| `rotateMaxSize` | number | `104857600` | Log rotation threshold (default 100MB) |

---

## Analysis Engine Installation

### Prerequisites

- Python >= 3.10

### Setup

```bash
cd claw_llm_doctor/analysis

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # or: .venv/bin/activate.fish

# Install dependencies
pip install click rich orjson

# Optional: accurate token counting
pip install tiktoken
```

---

## Usage

All commands accept these common options:

```
--file PATH          Single JSONL file to analyze
--log-dir PATH       Log directory (default: ~/.openclaw/logs/llm-doctor)
--session KEY        Filter to a specific session
--token-method       Token counting: char (fast) or tiktoken (accurate)
--format             Output: terminal (default), json, or html
-o, --output PATH    Output file path (for json/html)
```

### List sessions

```bash
claw-doctor sessions
```

Shows all captured sessions with record counts, LLM call counts, tool usage, and time ranges.

### Layer 1: Routing analysis

```bash
claw-doctor routing
```

Analyzes Primary vs Fallback model routing:
- Total calls, primary/fallback split, success rates
- Per-model and per-provider breakdown
- Error classification (auth_failed, rate_limited, timeout, context_length_exceeded, server_error)
- Routing timeline with time-ordered view of all LLM calls
- Fallback chain detection (cascading failures across models)
- Success rate over time (degradation detection in 10-min buckets)
- Fan-out ratio (user requests vs LLM calls)
- Per-session summary

Use `--primary-model ark/doubao-seed-2.0-code` to specify which model is primary (auto-detected from `~/.openclaw/openclaw.json` if available).

### Layer 3a: Context composition

```bash
claw-doctor context
```

Breaks down context window usage per turn:
- System prompt tokens
- Tool definition tokens
- Conversation history tokens
- Tool result tokens
- Thinking block tokens
- Utilization ratio with health indicator (green/yellow/red)
- Context growth curve (ASCII bar chart showing token growth per turn)
- Compaction event detection
- Large tool result warnings

### Layer 3b: System prompt ordering

```bash
claw-doctor prompt-order
```

Tracks system prompt section structure across turns:
- Detects sections: CORE, WORKSPACE, SKILL, MEMORY, COMPACT, TOOL, ENVIRONMENT
- Reports ordering stability (STABLE / UNSTABLE)
- Identifies order changes, content changes, and missing sections

### Layer 3c: System prompt compression

```bash
claw-doctor prompt-compression
```

Detects content loss from truncation or compaction:
- Baseline vs current length comparison
- Truncation marker detection (OpenClaw's 70/20/10 split)
- Similarity curve vs baseline across turns
- Compaction events with lost sections and preserved entities

### Layer 3d: Thinking process

```bash
claw-doctor thinking
```

Analyzes thinking block separation and quality:
- Thinking token ratio per turn
- Thinking category classification (planning, reasoning, tool_selection, code_review, self_correction)
- Leakage detection — thinking patterns in response content ("Let me think...", "I need to...", etc.)
- Leakage severity rating (none/low/medium/high)

### Session replay

```bash
claw-doctor replay --session agent:main:main
```

Renders a human-readable conversation timeline with color-coded events:
- User prompts (blue), assistant responses (green), tool calls (yellow)
- Agent lifecycle events (magenta), errors (red)
- Relative timestamps from session start

### Export raw records

```bash
claw-doctor export --session agent:main:main -o session.json
```

Dumps all raw JSONL records for a session as a JSON array, sorted by timestamp.

### Full report

```bash
# Terminal output
claw-doctor full

# HTML report
claw-doctor full --format html -o report.html

# JSON export
claw-doctor full --format json -o report.json

# Filter to one session
claw-doctor full --session sess-abc123

# Use accurate token counting
claw-doctor full --token-method tiktoken
```

### Quick-query with jq

The JSONL format supports direct querying:

```bash
# Count LLM calls per model
jq -r 'select(.type=="llm.input") | .model' llm-doctor-*.jsonl | sort | uniq -c

# Find all errors
jq 'select(.type=="llm.output" and .success==false)' llm-doctor-*.jsonl

# Token usage per call
jq 'select(.type=="llm.output" and .usage) | {model, input: .usage.input, output: .usage.output}' llm-doctor-*.jsonl

# Get all tool calls for a session
jq 'select(.type=="tool.start" and .sessionKey=="agent:main:main")' llm-doctor-*.jsonl
```

---

## JSONL Record Types

| Type | Trigger | Key Fields |
|------|---------|------------|
| `llm.input` | Before LLM call | model, provider, payload (systemPrompt, prompt, historyMessages, imagesCount) |
| `llm.output` | After LLM response | model, provider, payload (assistantTexts, lastAssistant), usage (input, output, cacheRead, cacheWrite, total) |
| `tool.start` | Before tool execution | toolName, params |
| `tool.end` | After tool execution | toolName, success, error, durationMs |
| `agent.start` | Agent begins | prompt |
| `agent.end` | Agent finishes | success, durationMs, error |
| `model.resolve` | Model routing | model, provider |

All records share: `type`, `ts`, `sessionKey`, `sessionId`, `agentId`, `runId`.

> **Note**: Primary/Fallback routing is not explicit in the SDK events. The analysis engine
> infers it by comparing each call's model against `agents.defaults.model.primary` from the
> OpenClaw config.

---

## License

MIT
