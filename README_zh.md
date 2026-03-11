# claw-llm-doctor

[![PyPI version](https://img.shields.io/pypi/v/claw-llm-doctor)](https://pypi.org/project/claw-llm-doctor/)
[![Python](https://img.shields.io/pypi/pyversions/claw-llm-doctor)](https://pypi.org/project/claw-llm-doctor/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[English](README.md) | [中文](README_zh.md)

[OpenClaw](https://github.com/openclaw) 诊断工具 -- 拦截、记录并分析 Agent 发出的每一次 LLM Provider 调用。

**claw-llm-doctor** 通过 OpenClaw Gateway 插件捕获完整的请求/响应，并提供 CLI 分析路由决策、上下文窗口组成、系统提示词完整性和思维过程质量。

## 安装

推荐使用 [uv](https://docs.astral.sh/uv/) 全局安装：

```bash
uv tool install git+https://github.com/fakechris/claw_llm_doctor.git
```

<details>
<summary>其他方式：使用 pipx 安装</summary>

```bash
pipx install git+https://github.com/fakechris/claw_llm_doctor.git
```
</details>

<details>
<summary>其他方式：在虚拟环境中安装</summary>

```bash
git clone https://github.com/fakechris/claw_llm_doctor.git
cd claw_llm_doctor
uv venv && source .venv/bin/activate
uv pip install .
```
</details>

> 发布到 PyPI 后：`uv tool install claw-llm-doctor` 或 `pipx install claw-llm-doctor`。

## 快速开始

**1. 启用插件**（自动安装到 OpenClaw Gateway）：

```bash
claw-llm-doctor enable
```

该命令会将拦截插件复制到 `~/.openclaw/extensions/`，运行 `npm install`，更新配置并重启守护进程。完成后，所有 LLM 调用都会被自动记录。

**2. 正常使用 OpenClaw。** 插件会将 JSONL 日志写入 `~/.openclaw/logs/llm-doctor/`。

**3. 分析数据：**

```bash
# 列出已捕获的会话
claw-llm-doctor sessions

# 运行完整诊断报告
claw-llm-doctor full

# 生成 HTML 报告
claw-llm-doctor full --format html -o report.html
```

## 分析能力

| 命令 | 分析层 | 分析内容 |
|------|--------|----------|
| `claw-llm-doctor routing` | LM 路由 | 主模型/备选分流、成功率、错误分类、降级链路、性能衰减检测 |
| `claw-llm-doctor context` | 上下文 | 每轮 token 分布（系统提示、工具、历史、思维）、利用率健康度、增长曲线 |
| `claw-llm-doctor prompt-order` | 提示词顺序 | Section 排列稳定性、压缩后的缺失检测 |
| `claw-llm-doctor prompt-compression` | 压缩分析 | 截断导致的内容丢失、与基线的相似度变化、压缩事件 |
| `claw-llm-doctor thinking` | 思维过程 | 思维/内容 token 比例、思维泄漏检测（内心独白出现在输出中） |
| `claw-llm-doctor replay --session KEY` | 回放 | 带颜色标记的对话时间线 |
| `claw-llm-doctor full` | 全部 | 所有分析层的综合报告 |

## 插件管理

```bash
claw-llm-doctor enable     # 安装并启用 OpenClaw 插件
claw-llm-doctor disable    # 禁用（保留文件）；加 --remove 可删除文件
claw-llm-doctor status     # 查看安装状态
```

### 插件配置

在 `~/.openclaw/openclaw.json` 中配置插件：

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

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `capturePayloads` | `true` | 记录完整的请求/响应载荷 |
| `redactSecrets` | `true` | 脱敏 API Key 和 Token |
| `maxPayloadSize` | `0` | 最大载荷大小（字节，0 = 不限） |
| `rotateMaxSize` | `104857600` | 日志轮转阈值（100 MB） |

## 通用选项

所有分析命令支持以下参数：

```
--file PATH          分析单个 JSONL 文件
--log-dir PATH       自定义日志目录
--session KEY        按会话过滤
--since TIME         只包含此时间之后的记录（如 '30m', '1h', '2026-03-11T10:00'）
--until TIME         只包含此时间之前的记录（格式同 --since）
--primary-model ID   指定主模型用于路由分类
--token-method       char（快速，默认）或 tiktoken（精确）
--format             terminal（默认）、json 或 html
-o, --output PATH    输出到文件
```

## 架构

```
┌─────────────────────────┐     JSONL      ┌──────────────────┐
│   OpenClaw Gateway      │ ──────────────> │  claw-llm-doctor CLI │
│   + llm-doctor 插件     │  ~/.openclaw/   │  (Python)        │
│   (TypeScript)          │  logs/          │                  │
└─────────────────────────┘                 └──────────────────┘
                                                     │
                                             ┌───────┴───────┐
                                             │    分析器      │
                                             │ routing       │
                                             │ context       │
                                             │ prompt-order  │
                                             │ compression   │
                                             │ thinking      │
                                             └───────┬───────┘
                                                     │
                                             ┌───────┴───────┐
                                             │    报告器      │
                                             │ terminal      │
                                             │ json          │
                                             │ html          │
                                             └───────────────┘
```

插件拦截 `llm_input`、`llm_output`、`before_tool_call`、`after_tool_call`、`agent_start`、`agent_end`、`compaction` 和 `diagnostic.usage` 事件。每个事件以单行 JSONL 格式写入，包含时间戳、会话上下文和可选载荷。

## JSONL 记录类型

每条记录包含顶层字段 `type`、`ts`、`sessionKey`、`sessionId`、`agentId`。部分类型还包含 `payload` 对象用于存储捕获的完整内容。

| 类型 | 关键字段（顶层，除非另行说明） |
|------|-------------------------------|
| `model.resolve` | prompt（模型选择前的路由决策） |
| `llm.input` | model, provider, runId, payload.{systemPrompt, prompt, historyMessages, imagesCount} |
| `llm.output` | model, provider, runId, success, durationMs, stopReason, payload.{assistantTexts, lastAssistant}, usage.{input, output, cacheRead, cacheWrite, total} |
| `tool.start` | toolName, toolCallId, params |
| `tool.end` | toolName, toolCallId, success, error, durationMs |
| `agent.start` | prompt, messageCount |
| `agent.end` | success, durationMs, error, messageCount |
| `compaction.before` | messageCount, compactingCount, tokenCount |
| `compaction.after` | messageCount, compactedCount, tokenCount |
| `diagnostic.usage` | model, provider, contextLimit, contextUsed, inputTokens, outputTokens, costUsd, durationMs |

### 使用 jq 快速查询

```bash
# 统计每个模型的 LLM 调用次数
jq -r 'select(.type=="llm.input") | .model' ~/.openclaw/logs/llm-doctor/*.jsonl | sort | uniq -c

# 查找所有错误
jq 'select(.type=="llm.output" and .success==false)' ~/.openclaw/logs/llm-doctor/*.jsonl

# 每次调用的 token 用量
jq 'select(.usage) | {model, input: .usage.input, output: .usage.output}' ~/.openclaw/logs/llm-doctor/*.jsonl
```

## 环境要求

- Python >= 3.10
- OpenClaw >= 2026.3.2（用于插件）
- Node.js >= 22.12.0（`enable` 命令运行 `npm install` 时需要）

## 贡献

欢迎贡献代码。请先开 Issue 讨论你想做的改动。

## 许可证

[MIT](LICENSE)
