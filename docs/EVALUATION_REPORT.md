# W6-2 受控评测报告

> 历史 development 报告：本文记录系统调优阶段的对照实验，不是最终泛化验收。后续 20 条 frozen holdout 已一次性执行，最终核心通过率为 `35.00%`，详见 [Frozen Holdout 最终验收](FINAL_ACCEPTANCE.md)。

## 结论

本轮在固定 development 数据、模型、数据库快照、参考时间、安全策略和超时配置下，对 baseline、retrieval、reranker 三种检索方案各运行 40 条案例，共保留 120 条真实 LangGraph 原始记录。三个方案的六个核心阶段通过率均为 `100%`；正确性打平时，baseline 平均延迟最低，reranker 最高。

这不是“通用 Agent 准确率 100%”。本轮只运行一次 development 集，且这些案例已用于定位和修复问题；未配置独立自然语言答案评审器。本报告完成时 frozen holdout 尚未运行，后续一次性结果见最终验收报告。

## 实验条件

| 条件 | 固定值 |
|---|---|
| 模型 | `qwen3:4b` |
| 数据集 | `retail-business-development-v1`，40 条 |
| 数据库快照 | `retail-demo-evaluation-2026-08-16-v1` |
| 参考时间 | `2026-08-16T12:00:00+08:00` |
| 时区 | `Asia/Shanghai` |
| SQL 安全策略 | `sqlglot-and-business-v1` |
| 权限策略 | `retail-access-v1` |
| 工作流超时 | `120000 ms` |
| 模型最大尝试 | `3` |
| 重复次数 | 每题每方案 `1` 次 |

唯一实验变量是检索适配器。Planner、SQL 生成、业务校验、数据库、权限、重试和评分器保持一致。

## 最终结果

| 方案 | 运行数 | 核心通过率 | 平均延迟 | 最低延迟 | 最高延迟 | 总重试 |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 40 | 100% | 3834.85 ms | 28 ms | 9026 ms | 1 |
| retrieval | 40 | 100% | 4100.68 ms | 28 ms | 9496 ms | 1 |
| reranker | 40 | 100% | 4877.08 ms | 27 ms | 10448 ms | 1 |

三个方案的 `plan / evidence / SQL / outcome / rows / chart` 阶段均为 `100%`。每个方案的结果分布相同：

| 结果 | 每方案 | 120 次合计 | 评测含义 |
|---|---:|---:|---|
| succeeded | 23 | 69 | 核心结果和总结成功 |
| degraded | 2 | 6 | 可信 rows 保留，语言总结按策略降级 |
| rejected | 10 | 30 | 越界或危险请求被正确拒绝 |
| approval_required | 3 | 9 | 合法高风险查询正确进入人工审批 |
| failed | 2 | 6 | 确定性故障按 Gold 预期失败 |

拒绝、审批和预期失败案例都没有访问 PostgreSQL。正确拒绝和正确进入审批本身是业务正确行为，不应被当作失败。

## 阶段评分

```text
PLAN      是否匹配人工 AnalysisPlan
EVIDENCE  是否命中最小充分 source_id
SQL       是否只读并符合指标、JOIN 和筛选契约
OUTCOME   是否命中预期的成功、拒绝、审批或失败状态
ROWS      PostgreSQL 结果是否精确匹配固定快照 Gold
CHART     ChartSpec 类型是否符合 Gold
ANSWER    独立自然语言回答评审，本轮未配置
```

`answer_score=None` 表示没有进行独立答案评审，不等于 0 分，也不能由核心通过率推导出自然语言回答准确率。

## 主要错误分析与修复

第一轮三个方案经常在相同案例和相同阶段失败，这说明共享组件比检索差异更值得优先检查。development 调优中定位并修复了：

- Planner 把“已支付”错误映射成状态分组；
- 客单价被误识别为订单数；
- 明确的渠道筛选被遗漏；
- SQL 对时间点直接分组，而不是按 `Asia/Shanghai` 自然日聚合；
- Decimal 小数位不同被字符串比较误判；
- 一条 development Gold 的默认 limit 与项目统一规则冲突。

提示词负责提供语义线索，Pydantic、SQLGlot 和业务一致性校验负责稳定兜底。执行器只保存原始状态，独立评分器才使用预先建立的 Gold 打分。

## 能力边界

- 只运行了 development，且案例已经用于定位和修复系统问题。
- 每题每方案只运行 1 次，不能评估随机模型的长期稳定性。
- 没有独立 Answer Judge，不能报告自然语言回答通过率。
- 本报告阶段 frozen holdout 尚未运行；后续已完成一次性验收，核心通过率为 `35.00%`，不能用本文 development 的 `100%` 替代该泛化结果。
- 当前数据只有 10 条演示订单，不能外推真实企业数据规模下的性能。
- 本轮正确性打平，不能宣称 reranker 比 baseline 更准确；其平均延迟反而更高。

## 可复现证据

- 原始报告：`evaluation/reports/w6_2_development_accepted.json`
- development 套件：`evaluation/business_development.json`
- 评分与执行：`evaluation_runs.py`、`evaluation_executors.py`
- 固定快照：`evaluation_snapshot.py`
- 完整回归：`358 passed`
- 功能与原始报告 commit：`9d5a8c4`

报告中的所有数字均来自原始 JSON，不使用预设简历指标；本轮 development 调优时没有读取 frozen holdout。冻结集后续已被正式消费，不得针对失败题调优后继续称其为独立验收。
