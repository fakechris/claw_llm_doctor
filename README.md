# claw-llm-doctor

[![PyPI version](https://img.shields.io/pypi/v/claw-llm-doctor)](https://pypi.org/project/claw-llm-doctor/)
[![Python](https://img.shields.io/pypi/pyversions/claw-llm-doctor)](https://pypi.org/project/claw-llm-doctor/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[English](README.md) | [中文](README_zh.md)

**Your AI agent is burning money and you can't see why.**

Every LLM call your [OpenClaw](https://github.com/openclaw) agent makes is a black box: which model handled it? Did it fall back silently? Is the context window filling up? Is the model's "thinking" leaking into user-visible output? How much of your prompt cache is actually hitting?

**claw-llm-doctor** answers all of these questions. One command to install, one command to diagnose.

```bash
pip install claw-llm-doctor
claw-llm-doctor enable   # hooks into OpenClaw Gateway
claw-llm-doctor full     # instant diagnostic report
```

## What You Get

> [**View a live demo report**](docs/demo-report.html) (self-contained HTML, no server needed)

### Executive Summary — One glance, all the numbers

```
  Analyzed 7 session(s), 224 LLM calls over 23.5h

               Key Metrics
┏━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ Metric                   ┃     Value ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━┩
│ Total requests           │       224 │
│ Success rate             │     52.7% │
│ Input tokens             │      6.3M │
│ Output tokens            │     65.8k │
│ Cache read tokens        │      7.7M │
│ Cache hit rate           │     55.0% │
│ Avg latency (success)    │   69869ms │
│ Avg throughput (success) │ 7.4 tok/s │
└──────────────────────────┴───────────┘

  Findings:
    • 106 failed call(s) (47.3% failure rate)
    • 7 fallback chain(s) detected
    • 2 turn(s) with thinking leakage
    • Model doubao-seed-2.0-code has 82.5% failure rate (99/120)
```

### 5 Analysis Layers — Every blind spot covered

| Layer | What it reveals | Why it matters |
|-------|----------------|---------------|
| **Routing** | Primary/fallback split, success rates, error classification, fallback chains | "82% of calls to our fallback model are silently failing" |
| **Context** | Token breakdown per turn, utilization curve, compaction events | "Context window hit 95% at turn 47 — that's when quality degraded" |
| **Prompt Integrity** | Section ordering stability, content loss after truncation | "The tool definitions section disappeared after compaction" |
| **Thinking** | Think/content ratio, leakage detection across 4 categories | "The model's inner monologue leaked into 3 user-facing responses" |
| **Performance** | E2E latency, throughput, cache hit rate per model | "Primary model averages 7.4 tok/s but fallback drops to 2.1" |

### Output Formats

- **Terminal** — Rich tables and color-coded output, perfect for quick checks
- **HTML** — Self-contained dark-theme report, share with your team
- **JSON** — Structured data for dashboards and automation

## Quick Start

**1. Install:**

```bash
pip install claw-llm-doctor
# or
uv tool install claw-llm-doctor
```

**2. Enable the plugin** (auto-installs into OpenClaw Gateway):

```bash
claw-llm-doctor enable
```

This copies the interceptor plugin to `~/.openclaw/extensions/`, runs `npm install`, updates your config, and restarts the daemon. All LLM calls are now recorded.

**3. Use OpenClaw as normal.** The plugin writes JSONL logs to `~/.openclaw/logs/llm-doctor/`.

**4. Diagnose:**

```bash
# Run full diagnostic (default: last 24h)
claw-llm-doctor full

# Generate a shareable HTML report
claw-llm-doctor full --format html -o report.html

# Analyze specific layers
claw-llm-doctor routing
claw-llm-doctor performance
claw-llm-doctor thinking

# Replay a session as a conversation timeline
claw-llm-doctor replay --session <KEY>

# Export raw data
claw-llm-doctor export --session <KEY> -o session.json
```

## Commands

| Command | Layer | Description |
|---------|-------|-------------|
| `routing` | LM Routing | Model routing decisions, success rates, error classification, fallback chains |
| `context` | Context | Token composition per turn, utilization health, growth curve |
| `prompt-order` | Prompt Integrity | Section ordering stability, missing sections after compaction |
| `prompt-compression` | Compression | Content loss from truncation, similarity vs baseline |
| `thinking` | Thinking | Thinking/content ratio, leakage detection (inner monologue in output) |
| `performance` | Performance | E2E latency, throughput (tok/s), cache hit rate per model |
| `full` | All | Combined report with executive summary |
| `sessions` | - | List all captured sessions |
| `replay` | - | Human-readable conversation timeline |
| `export` | - | Raw record export as JSON |

## Common Options

```
--since TIME         Time range start (default: 24h). '30m', '1h', '2h30m', 'all', or ISO datetime
--until TIME         Time range end
--session KEY        Filter to a specific session
--primary-model ID   Override primary model for routing classification
--format             terminal (default), json, or html
-o, --output PATH    Write output to file
--token-method       char (fast, default) or tiktoken (accurate)
```

## Plugin Management

```bash
claw-llm-doctor enable     # Install & enable the OpenClaw plugin
claw-llm-doctor disable    # Disable (keeps files); add --remove to delete
claw-llm-doctor status     # Check installation state
```

### Plugin Configuration

Configure in `~/.openclaw/openclaw.json`:

```json
{
  "plugins": {
    "entries": {
      "claw-llm-doctor": {
        "enabled": true,
        "settings": {
          "capturePayloads": true,
          "redactSecrets": true,
          "rotateMaxSize": 104857600
        }
      }
    }
  }
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `capturePayloads` | `true` | Record full request/response payloads |
| `redactSecrets` | `true` | Redact API keys and tokens |
| `maxPayloadSize` | `0` | Max payload size in bytes (0 = unlimited) |
| `rotateMaxSize` | `104857600` | Log rotation threshold (100 MB) |

## How It Works

```
┌─────────────────────────┐     JSONL      ┌──────────────────────┐
│   OpenClaw Gateway      │ ──────────────> │  claw-llm-doctor CLI │
│   + llm-doctor plugin   │  ~/.openclaw/   │  (Python)            │
│   (TypeScript)          │  logs/          │                      │
└─────────────────────────┘                 └──────────┬───────────┘
                                                       │
                                            ┌──────────┴──────────┐
                                            │     Analyzers       │
                                            │  routing · context  │
                                            │  prompt · thinking  │
                                            │    performance      │
                                            └──────────┬──────────┘
                                                       │
                                            ┌──────────┴──────────┐
                                            │     Reporters       │
                                            │  terminal · html    │
                                            │       json          │
                                            └─────────────────────┘
```

The plugin intercepts `llm_input`, `llm_output`, `tool_call`, `agent_start/end`, `compaction`, and `diagnostic.usage` events. Each event is written as a single JSONL line with timestamps, session context, and full payloads.

## Quick Query with jq

```bash
# Count LLM calls per model
jq -r 'select(.type=="llm.input") | .model' ~/.openclaw/logs/llm-doctor/*.jsonl | sort | uniq -c

# Find all errors
jq 'select(.type=="llm.output" and .success==false)' ~/.openclaw/logs/llm-doctor/*.jsonl

# Token usage per call
jq 'select(.usage) | {model, input: .usage.input, output: .usage.output}' ~/.openclaw/logs/llm-doctor/*.jsonl
```

## Requirements

- Python >= 3.10
- OpenClaw >= 2026.3.2 (for the plugin)
- Node.js >= 22.12.0 (for `npm install` during `enable`)

## Contributing

Contributions are welcome. Please open an issue first to discuss what you'd like to change.

## License

[MIT](LICENSE)
