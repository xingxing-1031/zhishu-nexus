# Frozen Holdout 最终验收

## 验收结论

本次使用独立 PostgreSQL 评测库、固定业务快照和本机 `qwen3:4b`，对当前 API 实际采用的 baseline 检索路径运行了 20 条 frozen holdout。评测只运行一次，未根据失败题修改提示词、规则或代码。

| 项目 | 结果 |
|---|---:|
| 冻结用例数 | 20 |
| 核心通过率 | 35.00% |
| 平均延迟 | 5689.90 ms |
| 最低延迟 | 45 ms |
| 最高延迟 | 14662 ms |
| 总重试次数 | 3 |

阶段通过率：

| 阶段 | 通过率 |
|---|---:|
| Plan | 45.45% |
| Evidence | 81.82% |
| SQL | 66.67% |
| Outcome | 60.00% |
| Rows | 47.37% |
| Chart | 90.91% |

`answer_pass_rate` 为 `null`，表示没有独立自然语言答案评审器，不能推导回答准确率。

## 可复现条件

- 数据集：`retail-business-final-holdout-v1`
- 数据库快照：`retail-demo-evaluation-2026-08-16-v1`
- 参考时间：`2026-08-16T12:00:00+08:00`
- 时区：`Asia/Shanghai`
- 模型：`qwen3:4b`
- 协议：`ollama`
- 检索策略：当前部署使用的 deterministic baseline
- 原始报告：`evaluation/reports/final_holdout.json`

独立评测数据库通过 `compose.evaluation.yaml` 启动，只加载原始 10 条订单和 6 条退款，不加载公网演示扩充数据。运行前，36 个可信 Gold 查询全部与固定快照匹配。

## 结果边界

这次结果证明评测链路能够发现 development 集之外的泛化问题，也说明当前版本不能宣称 Agent 准确率为 100%。简历可以描述已建立分阶段、可复现、无测试泄漏的评测体系，但不能把 development 的 100% 当作最终准确率。

本 frozen holdout 已被正式消费。后续不得根据具体失败题调优后继续引用同一文件作为独立最终验收；如果进行下一轮系统优化，应使用新的 development 证据，并重新建立未见过的独立 holdout。
