# claw-llm-doctor

[![PyPI version](https://img.shields.io/pypi/v/claw-llm-doctor)](https://pypi.org/project/claw-llm-doctor/)
[![Python](https://img.shields.io/pypi/pyversions/claw-llm-doctor)](https://pypi.org/project/claw-llm-doctor/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[English](README.md) | [中文](README_zh.md)

**你的 AI Agent 在烧钱，而你完全看不到原因。**

每一次 [OpenClaw](https://github.com/openclaw) Agent 发出的 LLM 调用都是黑盒：哪个模型在处理？是不是悄悄降级到了备选模型？上下文窗口快满了吗？模型的"思维过程"有没有泄露到用户可见的回复里？Prompt Cache 命中率到底是多少？

**claw-llm-doctor** 一条命令安装，一条命令看透所有问题。

```bash
pip install claw-llm-doctor
claw-llm-doctor enable   # 挂载到 OpenClaw Gateway
claw-llm-doctor full     # 一键诊断报告
```

## 你会得到什么

> [**查看 Demo 报告**](docs/demo-report.html)（自包含 HTML，无需服务器）

### 执行摘要 — 一眼看清全局

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

### 5 层分析 — 覆盖每一个盲区

| 分析层 | 能发现什么 | 为什么重要 |
|--------|-----------|-----------|
| **路由** | 主模型/备选分流、成功率、错误分类、降级链路 | "备选模型 82% 的调用在静默失败" |
| **上下文** | 每轮 Token 分布、利用率曲线、压缩事件 | "第 47 轮上下文窗口达到 95%——质量就是从这里开始劣化的" |
| **提示词完整性** | Section 排列稳定性、截断后的内容丢失 | "工具定义在压缩后消失了" |
| **思维过程** | 思维/内容比例、4 类泄漏检测 | "模型的内心独白泄露到了 3 条用户可见的回复中" |
| **性能** | 端到端延迟、吞吐量、每模型 Cache 命中率 | "主模型 7.4 tok/s，备选模型降到 2.1" |

### 输出格式

- **终端** — Rich 表格 + 彩色标记，适合快速排查
- **HTML** — 自包含暗色主题报告，分享给团队
- **JSON** — 结构化数据，接入仪表盘和自动化流水线

## 快速开始

**1. 安装：**

```bash
pip install claw-llm-doctor
# 或
uv tool install claw-llm-doctor
```

**2. 启用插件**（自动安装到 OpenClaw Gateway）：

```bash
claw-llm-doctor enable
```

自动将拦截插件复制到 `~/.openclaw/extensions/`，运行 `npm install`，更新配置并重启守护进程。完成后所有 LLM 调用都会被记录。

**3. 正常使用 OpenClaw。** 插件将 JSONL 日志写入 `~/.openclaw/logs/llm-doctor/`。

**4. 诊断：**

```bash
# 完整诊断（默认最近 24 小时）
claw-llm-doctor full

# 生成可分享的 HTML 报告
claw-llm-doctor full --format html -o report.html

# 分层分析
claw-llm-doctor routing
claw-llm-doctor performance
claw-llm-doctor thinking

# 回放某个会话
claw-llm-doctor replay --session <KEY>

# 导出原始数据
claw-llm-doctor export --session <KEY> -o session.json
```

## 命令列表

| 命令 | 分析层 | 说明 |
|------|--------|------|
| `routing` | LM 路由 | 模型路由决策、成功率、错误分类、降级链路 |
| `context` | 上下文 | 每轮 Token 组成、利用率健康度、增长曲线 |
| `prompt-order` | 提示词完整性 | Section 排列稳定性、压缩后缺失检测 |
| `prompt-compression` | 压缩分析 | 截断导致的内容丢失、与基线的相似度变化 |
| `thinking` | 思维过程 | 思维/内容比例、泄漏检测（内心独白出现在输出中） |
| `performance` | 性能 | 端到端延迟、吞吐量 (tok/s)、每模型 Cache 命中率 |
| `full` | 全部 | 含执行摘要的综合报告 |
| `sessions` | - | 列出所有已捕获的会话 |
| `replay` | - | 可读的对话时间线 |
| `export` | - | 导出原始 JSON 记录 |

## 通用选项

```
--since TIME         起始时间（默认 24h）。'30m', '1h', '2h30m', 'all', 或 ISO 日期时间
--until TIME         截止时间
--session KEY        按会话过滤
--primary-model ID   指定主模型用于路由分类
--format             terminal（默认）、json 或 html
-o, --output PATH    输出到文件
--token-method       char（快速，默认）或 tiktoken（精确）
```

## 插件管理

```bash
claw-llm-doctor enable     # 安装并启用 OpenClaw 插件
claw-llm-doctor disable    # 禁用（保留文件）；加 --remove 可删除文件
claw-llm-doctor status     # 查看安装状态
```

### 插件配置

在 `~/.openclaw/openclaw.json` 中配置：

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

## 工作原理

```
┌─────────────────────────┐     JSONL      ┌──────────────────────┐
│   OpenClaw Gateway      │ ──────────────> │  claw-llm-doctor CLI │
│   + llm-doctor 插件     │  ~/.openclaw/   │  (Python)            │
│   (TypeScript)          │  logs/          │                      │
└─────────────────────────┘                 └──────────┬───────────┘
                                                       │
                                            ┌──────────┴──────────┐
                                            │       分析器         │
                                            │  routing · context  │
                                            │  prompt · thinking  │
                                            │    performance      │
                                            └──────────┬──────────┘
                                                       │
                                            ┌──────────┴──────────┐
                                            │       报告器         │
                                            │  terminal · html    │
                                            │       json          │
                                            └─────────────────────┘
```

插件拦截 `llm_input`、`llm_output`、`tool_call`、`agent_start/end`、`compaction` 和 `diagnostic.usage` 事件。每个事件以单行 JSONL 格式写入，包含时间戳、会话上下文和完整载荷。

## 使用 jq 快速查询

```bash
# 统计每个模型的 LLM 调用次数
jq -r 'select(.type=="llm.input") | .model' ~/.openclaw/logs/llm-doctor/*.jsonl | sort | uniq -c

# 查找所有错误
jq 'select(.type=="llm.output" and .success==false)' ~/.openclaw/logs/llm-doctor/*.jsonl

# 每次调用的 Token 用量
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
