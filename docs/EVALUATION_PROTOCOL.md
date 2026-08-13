# Agent Development 评测协议

## 目的

评测 Agent Runtime 的结构化行为，不把规则样本的通过率写成通用大模型准确率。每次报告必须保留样本级记录、数据集版本、运行配置和代码提交。

## 当前确定性报告

`evaluation/reports/agent-development-deterministic.json` 使用 `agent_development.jsonl` 的 5 条 synthetic development 样本和假的 Tool Registry，验证路由、拒答、工具白名单和最低证据要求。当前结果为：

| 指标 | 结果 |
|---|---:|
| 样本数 | 5 |
| Skill 路由准确率 | 1.0 |
| 拒答准确率 | 1.0 |
| 工具白名单准确率 | 1.0 |
| 最低证据完整性 | 1.0 |

“最低证据完整性”只检查样本声明的必需证据是否出现；额外的安全证据不会被判为失败。它不是 SQL 正确率、RAG Recall、模型答案质量或线上延迟。

## 真实评测命令

```powershell
.\.venv\Scripts\python.exe scripts/run_agent_development.py
.\.venv\Scripts\python.exe -m pytest -q
```

接入真实 Qwen、PostgreSQL 和项目二 `/internal/evidence` 后，另存一份带时间戳的真实报告，至少记录：请求成功/降级/拒答率、Skill 路由、工具选择、SQL 执行成功率、证据完整性、P50/P95、输入输出 Token 和服务配置哈希。未实测的数字不写入简历。

## 线上 Agent development 最终报告

最终报告为 `evaluation/reports/agent-live-development-20260813T220105Z.json`，`latest` 文件与其 SHA-256 完全一致。运行时间为 2026-08-14（Asia/Shanghai），条件如下：

| 条件 | 固定值 |
|---|---|
| 数据集 | `agent_live_development.jsonl`，12 条 live development 样本 |
| 项目一运行版本 | `33e673ce92857980034d85ea0a50b0d69efe5143` |
| 项目二运行版本 | `4b3f6cc5cb5420c1b321680ffdb279afef7cdc32` |
| 模型 | 项目一/项目二均为远程 `qwen-plus` |
| 检索 | `text-embedding-v3` + `hybrid_rrf_reranker` + `qwen3-rerank` |
| 数据与工具 | 公网 VPS、PostgreSQL、项目二 Evidence API、MCP Markdown 导出 |
| 上下文预算 | 每题 `1600` token 的服务端确定性估算预算 |
| 并发 | 串行；本次限流重试 `0` 次 |

最终结果：

| 指标 | 结果 | 口径 |
|---|---:|---|
| 逐题通过率 | `91.67%`（11/12） | 状态、Skill、工具序列、证据、导出、工具状态和上下文预算全部满足样本要求 |
| 业务非失败率 | `100%`（8/8） | 5 条 `succeeded`、3 条可信 `degraded`，无业务题失败或拒答 |
| Skill 路由 | `100%`（12/12） | 退款、渠道、商品、周报和越界请求 |
| 工具选择 | `100%`（12/12） | 严格比较每题工具序列 |
| 证据要求 | `100%`（12/12） | 需要数据/制度证据的样本均满足最低要求 |
| 拒答 | `100%`（4/4） | 删除、更新、天气、库存越界 |
| 工具调用成功率 | SQL/RAG/MCP 均 `100%` | 以报告中的每次 ToolCallRecord 为准 |
| 上下文预算合规 | `100%`，最大占用 `5.5%` | 只表示 ContextBuilder 的结构化上下文估算，不是模型总输入输出 Token |
| 端到端延迟 | P50 `16.181s`，P95 `29.535s` | 12 条混合样本，包含 4 条快速拒答 |

唯一未完全通过的样本是退款率复盘：SQL、RAG、MCP、数据证据和制度证据均成功，但自然语言总结服务临时不可用，系统返回 `degraded` 并保留 4 行可信查询结果。该样本证明降级边界生效，不能改写成“系统失败”，也不能为了得到 100% 重复运行后挑选更好的一次。

本数据集在运行过程中用于定位并修复了周报 Skill 的指标契约、复合问题的 SQL/RAG 子任务拆分和公开限流适配，因此只能称为线上 development 结果，不能称为 frozen holdout、通用准确率或生产 SLA。项目二已有的 8 条 frozen holdout 保持冻结，不因本轮联调重跑或调参。

复现命令：

```powershell
$env:AGENT_DEMO_PASSWORD='<仅在当前进程设置>'
.\.venv\Scripts\python.exe scripts\run_agent_live_development.py
```
