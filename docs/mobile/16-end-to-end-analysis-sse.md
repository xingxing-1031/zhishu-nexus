# W4-4 手机学习卡：真实模型端到端分析与 SSE

## 1. 本阶段解决什么问题

前几阶段已经分别完成结构化计划、指标证据、SQL 安全、数据库执行和工作流骨架。W4-4 把它们接成一条真实链路：

```text
自然语言问题
→ qwen3:4b 生成 AnalysisPlan
→ 检索 RetrievalEvidence
→ qwen3:4b 生成 SQL
→ SQLGlot 安全校验
→ PostgreSQL 只读执行
→ qwen3:4b 解释真实结果
→ 确定性生成图表规格
→ FastAPI 返回同步结果或 SSE 状态
```

模型不能绕过计划、证据、安全校验和数据库执行中的任何一层。

## 2. 为什么 SQL 生成需要计划和证据

`AnalysisPlan` 说明用户本次想做什么：指标、维度、筛选、时间范围、排序和限制。

`RetrievalEvidence` 说明业务中批准的计算依据：公式、固定筛选、来源字段、表和 JOIN。

只给计划，模型不知道可靠公式和数据库关系；只给证据，模型不知道本次用户选择了什么。因此两者共同构成 SQL 生成输入。

## 3. 三个模型契约

工作流没有让节点直接绑定 Ollama，而是定义三个稳定契约：

```text
AnalysisPlanner：问题 → AnalysisPlan
SQLGenerator：问题 + 计划 + 证据 + 上次错误 → SQL
ResultSummarizer：问题 + 计划 + 真实查询行 → 文字结论
```

Ollama 只是当前适配器。以后更换模型服务时，节点职责和工作流结构不需要一起重写。

## 4. Pydantic 与 SQLGlot 分别拦截什么

Pydantic 检查的是结构化计划。例如未知指标、不支持的筛选字段、错误操作符、非法时间范围和无关排序字段会在 SQL 生成前被拒绝。

SQLGlot 检查的是已经生成的 SQL。例如 `DELETE FROM orders`、`SELECT *`、非法表字段和隐藏写操作会在数据库执行前被拒绝。

```text
计划错误 → Pydantic
SQL 结构或安全错误 → SQLGlot
执行超时或连接错误 → PostgreSQL 执行层
```

## 5. 为什么建立模型专用计划格式

直接把完整 `AnalysisPlan` JSON Schema 交给当前 Ollama 时，嵌套模型和联合类型导致 grammar 解析失败。临时改用普通 JSON 后，模型又把“最近 30 天”错误写成 `day between`。

最终方案是建立更简单的模型专用 Schema：

```text
time_range_days 只能是 0 到 365
filters 只能使用批准字段和 equals/in
sort 只能使用批准字段和方向
limit 不能超过请求 max_rows
禁止额外字段
```

模型输出再转换并通过正式 `AnalysisPlan` 校验。这是适配外部模型格式能力，不是取消业务校验。

## 6. SQL 拒绝后的重试

SQLGlot 拒绝模型 SQL 后，工作流不会执行数据库查询，而是把错误写入 `sql_validation_error`，再交给 SQL 生成节点。

```text
校验通过 → execute_sql
校验失败且还有次数 → generate_sql
校验失败且次数耗尽 → fail
```

重新生成时会清除旧的 `PreparedSQL` 和校验状态，防止误用上一轮结果。

## 7. 图表规格是什么

后端不直接生成图片，而是返回通用绘图说明：

```json
{
  "chart_type": "bar",
  "x_field": "channel",
  "y_fields": ["sales_amount"]
}
```

未来前端 ECharts 读取规格和查询行后绘图。分类维度使用柱状图，日期维度使用折线图，无维度总值使用 KPI；零行结果不生成误导性图表。

图表规格只能引用查询结果真实存在的字段。若计划要求 `sales_amount`，结果却只有 `profit`，确定性图表校验会拒绝。

## 8. 为什么 FastAPI 必须调用完整工作流

`POST /analysis/run` 只负责接收 `AnalysisRequest`、调用 `AnalysisRunner` 和返回 `AnalysisResponse`。

如果接口直接调用 SQL 模型，就会跳过计划校验、业务证据、SQL 安全、审计、有限重试和结果字段检查。完整 LangGraph 用固定节点和条件边强制执行这些步骤，不只是用提示词劝模型遵守。

公开响应包含答案、计划、数据行、图表规格、证据来源、重试次数和节点轨迹，不直接暴露模型内部思考。

## 9. 同步接口与 SSE

同步接口在全部流程完成后一次返回结果，调用简单，但用户等待期间不知道进度。

SSE 使用一条 HTTP 连接，由服务器连续向页面发送事件：

```text
status：请求已接收
status：计划完成
status：证据检索完成
status：SQL 生成完成
status：安全校验完成
status：数据库查询完成
status：总结和图表完成
result：最终结构化响应
```

SSE 展示可审计状态，不展示模型隐藏思考过程。节点状态来自真实工作流轨迹，而不是模型编写的解释。

## 10. 为什么流中错误仍是事件

普通接口可以在执行前决定返回 200、422、500 或 502。但 SSE 一旦已经发送首个事件，HTTP 响应头通常已经是 200，后面不能再改成 500。

因此流式执行中途失败时发送：

```text
event: error
data: {...}
```

前端监听 `error` 事件并显示失败状态。HTTP 连接成功不等于分析任务成功，必须继续判断 SSE 事件类型。

## 11. 真实验证结果

真实问题：`最近30天各渠道销售额是多少？`

```text
计划：sales_amount + channel + 30 天 + 降序 + 10 行
证据：销售额 v1、orders、order_items、批准 JOIN
数据：京东 11300.00；淘宝 9000.00
图表：bar，x=channel，y=sales_amount
重试：0
轨迹：plan → retrieve → generate_sql → validate_sql
      → execute_sql → summarize
```

同步 HTTP 和 SSE 都通过真实 `qwen3:4b`、SQLGlot 与 PostgreSQL 验证。当前结果基于种子数据和一个受控场景，不能外推为生产准确率。

## 12. 当前边界

已完成真实模型端到端链路、同步接口、SSE 和确定性图表规格，但还没有实现真正的前端 ECharts 页面，也没有完成生产只读数据库账号、角色权限、HITL、完整故障注入或大规模自然语言评测。

## 13. 自测题

1. `AnalysisPlan` 和 `RetrievalEvidence` 分别提供什么？
2. 为什么 SQL 生成必须同时拿到计划和证据？
3. 三个模型契约分别负责什么？
4. Pydantic 和 SQLGlot 分别拦截哪类错误？
5. 为什么完整 Pydantic Schema 没有直接交给当前 Ollama？
6. 模型专用计划格式是否取消了正式 Pydantic 校验？
7. SQLGlot 拒绝 SQL 后工作流怎样处理？
8. 为什么重新生成 SQL 时要清空旧校验状态？
9. 图表规格与固定图片有什么区别？
10. 为什么图表规格只能引用查询结果中的字段？
11. 为什么 FastAPI 不能直接调用 SQL 模型？
12. 同步接口和 SSE 的主要区别是什么？
13. SSE 是否展示模型内部思考过程？
14. 为什么 SSE 中途失败后不能再把 HTTP 状态改成 500？
15. 当前真实端到端验证能证明什么，不能证明什么？

## 14. 自测题标准答案

1. 计划表达本次用户意图和约束；证据提供批准的业务公式、固定筛选、字段、表和 JOIN。
2. 计划单独缺少可靠口径和 Schema，证据单独缺少本次请求意图，两者缺一都可能生成业务错误 SQL。
3. Planner 生成计划，SQLGenerator 根据计划和证据生成 SQL，ResultSummarizer 只根据真实结果生成结论。
4. Pydantic 拦截计划结构和业务字段错误；SQLGlot 拦截 SQL 结构、表字段和读写安全错误。
5. 当前 Ollama 无法为包含复杂嵌套和联合类型的完整 Schema 初始化 grammar，因此使用更简单的模型专用 Schema。
6. 没有。模型输出仍会转换为正式 `AnalysisPlan`，再次接受 Pydantic 枚举、边界和跨字段校验。
7. 保存拒绝原因；有重试次数时返回 SQL 生成节点，次数耗尽后进入失败节点，始终不会执行被拒绝 SQL。
8. 防止下一轮错误使用上一轮已经失效的 `PreparedSQL` 或 `sql_valid` 状态。
9. 图表规格是可检查、可复用的绘图说明，前端可以按屏幕和交互需要渲染；固定图片缺少原始字段关系和交互能力。
10. 防止模型或展示层编造 `profit` 等数据库结果中不存在的数据。
11. 直接调用会绕过计划、证据、安全、审计、重试和结果检查；完整工作流强制这些节点按顺序执行。
12. 同步接口完成后一次返回；SSE 在同一 HTTP 连接中连续返回状态事件和最终结果。
13. 不展示。SSE 只展示节点状态、结果或错误，不暴露隐藏推理。
14. 首个事件发送后 HTTP 响应头已经确定，只能在事件流中用 `event: error` 表示任务失败。
15. 证明一个受控零售问题能真实经过模型、安全层和数据库得到正确结果；不证明所有自然语言、指标和生产故障都已覆盖。
