# W6-2 手机学习卡：单次运行与阶段评分

## 这一步解决什么问题？

W6-1 只规定了题目和人工 Gold，W6-2 才规定一次 Agent 运行如何被记录和评分。不能只保存“最终回答正确率”，否则无法知道错误来自计划、检索、SQL、安全边界、数据库结果还是总结。

## 一次运行记录什么？

`EvaluationRunRecord` 是某个 case 的一次原始运行快照，至少记录：

```text
case_id / variant / run_index
actual_plan / actual_source_ids
actual_sql / sql_safe / evidence_match
actual_rows / actual_reason_code / actual_chart_type
actual_outcome / database_called
answer_correct / latency_ms / retry_count / trace
```

`run_index` 很重要。同一个问题运行三次，必须保留三条记录，不能只留下最好的一次。

## 阶段怎么评分？

```text
PLAN    计划是否等于人工 Gold AnalysisPlan
EVIDENCE 检索 source_id 是否等于最小充分证据
SQL     是否有 SQL、只读，并且与 Evidence 一致
OUTCOME 是否命中 succeeded / rejected / approval_required / failed 边界
ROWS    PostgreSQL 结果是否精确等于固定快照 Gold rows
CHART   图表类型是否符合 Gold 规格
ANSWER  总结是否正确引用并解释 rows
```

核心结果分只看前六个业务和安全阶段；回答分单独计算。这样 SQL 和 rows 正确、总结模型失败时，核心结果仍然是 1，但回答分为 0，整体属于 `degraded`，而不是把真实数据也判成失败。

## 为什么不能只看最终回答？

模型可能给出流畅但错误的总结，也可能总结服务失败但表格数据已经正确。两者业务含义不同：前者是核心结果失败，后者是可降级。阶段评分把问题定位到具体层。

## 多次运行怎么汇总？

同一 variant 的全部运行一起统计：

```text
core_pass_rate
answer_pass_rate
每个阶段的通过率
平均/最低/最高延迟
总重试次数
```

不能看完结果后挑最高分；随机模型必须报告波动和稳定性。

## 对照实验必须固定什么？

`ControlledExperiment` 只允许使用 `development`。不同方案之间必须保持以下条件完全一致：

```text
模型
评测集版本
数据库快照
reference_time / timezone
SQL 安全策略版本
权限策略版本
超时配置
```

如果同时改了模型和检索，就无法证明准确率变化到底来自哪一个因素。`ensure_comparable_conditions` 会在比较前拒绝条件不一致的实验。

## 标准口述答案

W6-2 先建立单次运行记录和阶段级评分。一次运行不仅保存最终答案，还保存分析计划、检索 source_id、生成 SQL、安全校验结果、Evidence 一致性、数据库 rows、图表、回答、延迟、重试和 Trace。评分分为计划、证据、SQL、安全、结果行、图表和回答几个阶段。核心结果分与完整回答分必须拆开，因为 SQL 和数据库结果正确时，总结模型可能暂时失败，这时应该是 degraded；反过来，如果数据错了，即使语言流畅也不能算成功。对同一题的多次运行要按 run_index 全部保存，再计算平均分、每阶段通过率、延迟范围和重试次数，不能只报告最好的一次。W6-2 当前只完成评分契约和纯函数测试，还没有把三种真实 Agent 方案全部跑完，也没有使用 holdout 调参。

## 自测提纲

1. `AnalysisPlan` 和 `RetrievalEvidence` 分别回答什么问题？
2. SQLGlot 通过但 Evidence 不匹配，为什么仍然不能执行？
3. rows 正确但总结失败，核心结果分和回答分分别是多少？
4. 为什么一次实验必须保存 `run_index` 和全部原始输出？
5. `development` 和 `holdout` 在这一步分别怎么使用？

## development 运行器做什么？

`run_development_experiment` 只负责实验调度：确认套件是未冻结的 development、确认数据版本、数据库快照、参考时间和时区一致，再让每个 variant 的 executor 对每道题运行指定次数，保存每条原始运行记录，逐条评分，最后汇总成 `ExperimentReport`。它不负责调用模型、检索、生成 SQL 或连接 PostgreSQL；这些具体实现必须由 executor 提供。

这里不能把现有的 Hybrid/Reranker 代码直接塞进 `CatalogRetrievalTool.retrieve(plan)` 后就宣称完成公平对照。目录检索是已经有 `AnalysisPlan` 后的确定性证据查找，而 Hybrid/Reranker 是从原始自然语言召回指标的另一条链路，输入输出契约不同。下一步要先明确 baseline、retrieval、reranker 各自改变的唯一变量，再分别实现 executor。

## 为什么需要内部评测观测？

普通用户响应只需要结论、rows 和图表，不应暴露生成 SQL、数据库错误和全部内部状态。评测 executor 却需要这些原始字段定位错误，因此 `AnalysisEvaluationObservation` 从可信 LangGraph 快照中复制 plan、Evidence source_id、SQL、安全状态、rows、chart、answer、错误、重试和 Trace，再交给 executor 转换为运行记录。它不会修改工作流，也不会把内部字段加入公开 FastAPI 响应。

当前观测对象故意没有 `evidence_match`。项目只有评分字段，还没有实现运行时 SQL 与 Evidence 业务一致性校验，不能因为 SQL 可执行或结果成功就伪造为一致。后续必须由专用一致性校验器基于 SQLGlot AST、AnalysisPlan、Evidence 和指标字典给出这个结论。
