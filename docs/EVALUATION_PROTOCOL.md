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
