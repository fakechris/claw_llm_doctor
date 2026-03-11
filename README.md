# claw-llm-doctor

[![PyPI version](https://img.shields.io/pypi/v/claw-llm-doctor)](https://pypi.org/project/claw-llm-doctor/)
[![Python](https://img.shields.io/pypi/pyversions/claw-llm-doctor)](https://pypi.org/project/claw-llm-doctor/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[English](README.md) | [中文](README_zh.md)

Diagnostic toolkit for [OpenClaw](https://github.com/openclaw) -- intercept, record, and analyze every LLM Provider call your agent makes.

**claw-llm-doctor** captures full request/response payloads via an OpenClaw Gateway plugin and provides a CLI to analyze routing decisions, context window composition, system prompt integrity, and thinking process quality.

## Installation

```bash
pip install git+https://github.com/fakechris/claw_llm_doctor.git
```

<details>
<summary>Alternative: install with uv</summary>

```bash
uv pip install git+https://github.com/fakechris/claw_llm_doctor.git
```
</details>

<details>
<summary>Alternative: install from local clone</summary>

```bash
git clone https://github.com/fakechris/claw_llm_doctor.git
cd claw_llm_doctor
pip install .
```
</details>

> Once published to PyPI, you will also be able to run `pip install claw-llm-doctor`.

## Quick Start

**1. Enable the plugin** (auto-installs into OpenClaw Gateway):

```bash
claw-doctor enable
```

This copies the interceptor plugin to `~/.openclaw/extensions/`, runs `npm install`, updates your config, and restarts the daemon. That's it -- all LLM calls are now being recorded.

**2. Use OpenClaw as normal.** The plugin writes JSONL logs to `~/.openclaw/logs/llm-doctor/`.

**3. Analyze:**

```bash
# List captured sessions
claw-doctor sessions

# Run full diagnostic report
claw-doctor full

# Generate an HTML report
claw-doctor full --format html -o report.html
```

## What It Analyzes

| Command | Layer | What It Reveals |
|---------|-------|-----------------|
| `claw-doctor routing` | LM Routing | Primary/fallback split, success rates, error classification, fallback chains, degradation detection |
| `claw-doctor context` | Context | Token breakdown per turn (system, tools, history, thinking), utilization health, growth curve |
| `claw-doctor prompt-order` | Prompt Order | Section ordering stability, missing sections after compaction |
| `claw-doctor prompt-compression` | Compression | Content loss from truncation, similarity vs baseline, compaction events |
| `claw-doctor thinking` | Thinking | Thinking/content ratio, leakage detection (inner monologue in output) |
| `claw-doctor replay --session KEY` | Replay | Human-readable conversation timeline with color-coded events |
| `claw-doctor full` | All | Combined report across all layers |

## Plugin Management

```bash
claw-doctor enable     # Install & enable the OpenClaw plugin
claw-doctor disable    # Disable (keeps files); add --remove to delete
claw-doctor status     # Check installation state
```

### Plugin Configuration

The plugin can be configured in `~/.openclaw/openclaw.json`:

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

## Common Options

All analysis commands accept:

```
--file PATH          Analyze a single JSONL file
--log-dir PATH       Custom log directory
--session KEY        Filter to a specific session
--primary-model ID   Override primary model for routing classification
--token-method       char (fast, default) or tiktoken (accurate)
--format             terminal (default), json, or html
-o, --output PATH    Write output to file
```

## Architecture

```
┌─────────────────────────┐     JSONL      ┌──────────────────┐
│   OpenClaw Gateway      │ ──────────────> │  claw-doctor CLI │
│   + llm-doctor plugin   │  ~/.openclaw/   │  (Python)        │
│   (TypeScript)          │  logs/          │                  │
└─────────────────────────┘                 └──────────────────┘
                                                     │
                                             ┌───────┴───────┐
                                             │   Analyzers   │
                                             │ routing       │
                                             │ context       │
                                             │ prompt-order  │
                                             │ compression   │
                                             │ thinking      │
                                             └───────┬───────┘
                                                     │
                                             ┌───────┴───────┐
                                             │  Reporters    │
                                             │ terminal      │
                                             │ json          │
                                             │ html          │
                                             └───────────────┘
```

The plugin intercepts `llm_input`, `llm_output`, `before_tool_call`, `after_tool_call`, `agent_start`, `agent_end`, `compaction`, and `diagnostic.usage` events. Each event is written as a single JSONL line with timestamps, session context, and optional payloads.

## JSONL Record Types

Every record has top-level `type`, `ts`, `sessionKey`, `sessionId`, and `agentId` fields. Some types carry an additional `payload` object for captured content.

| Type | Key Fields (top-level unless noted) |
|------|--------------------------------------|
| `model.resolve` | prompt (routing decision before model selection) |
| `llm.input` | model, provider, runId, payload.{systemPrompt, prompt, historyMessages, imagesCount} |
| `llm.output` | model, provider, runId, success, durationMs, stopReason, payload.{assistantTexts, lastAssistant}, usage.{input, output, cacheRead, cacheWrite, total} |
| `tool.start` | toolName, toolCallId, params |
| `tool.end` | toolName, toolCallId, success, error, durationMs |
| `agent.start` | prompt, messageCount |
| `agent.end` | success, durationMs, error, messageCount |
| `compaction.before` | messageCount, compactingCount, tokenCount |
| `compaction.after` | messageCount, compactedCount, tokenCount |
| `diagnostic.usage` | model, provider, contextLimit, contextUsed, inputTokens, outputTokens, costUsd, durationMs |

### Quick-query with jq

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
