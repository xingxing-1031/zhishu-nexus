# W3-3 手机学习卡：工作流工具契约

## 1. 本阶段解决什么问题

W3-1 定义了 LangGraph 工作流骨架，W3-2 定义了结构化 `AnalysisPlan`。W3-3 把检索、SQL 校验和 SQL 执行封装为稳定工具契约，让节点不需要包含 SQLGlot、数据库连接、事务和审计的全部细节。

```text
节点：读取 State、调用工具、写回结果
工具契约：规定输入、输出和错误类型
适配器：把契约连接到现有底层实现
底层实现：真正完成 SQLGlot 校验或 PostgreSQL 查询
```

## 2. 工具与 MCP 的区别

当前工具是项目内部的 Python 能力，不是 MCP。

```text
Python 工具 = 项目内部可以调用的能力
MCP = 将工具通过统一协议提供给外部 Agent 或客户端
```

内部契约稳定且确有跨进程调用需求时，才需要增加 MCP 层。

## 3. 三个工具契约

### RetrievalTool

```text
输入：AnalysisPlan
输出：RetrievalEvidence 列表
```

每条证据包含：

- `source_id`：指标定义、Schema 或业务规则的来源编号。
- `content`：检索到的具体知识。

当前只有契约，真实指标字典和 RAG 在 W4 实现。

### SQLValidationTool

```text
输入：request_id、user_id、原始 SQL、max_rows
输出：PreparedSQL
失败：SQLValidationToolError
```

真实调用链：

```text
SQLGlotValidationTool.validate()
-> prepare_audited_sql()
-> prepare_safe_sql()
-> SQLGlot AST 与访问边界校验
```

`SQLValidationTool` 是 `Protocol`，只规定 `validate()` 的形状；方法体中的 `...` 没有实现功能。`SQLGlotValidationTool` 是当前真实适配器。

### SQLExecutionTool

```text
输入：request_id、user_id、original_sql、prepared_sql
输出：SafeQueryResult
失败：SQLExecutionToolError
```

`original_sql` 用于审计模型最初生成了什么，`prepared_sql` 才交给 PostgreSQL 执行。

## 4. SQL 拒绝链路

```text
模型生成 DELETE FROM orders
-> validate_sql 节点调用 SQLValidationTool
-> SQLGlot 拒绝
-> 写入 rejected 审计
-> prepared_sql = None
-> sql_valid = False
-> sql_validation_error = 拒绝原因
-> retry_count += 1
-> 条件边选择 generate_sql 或 fail
```

危险 SQL 不会作为业务查询执行。若使用数据库审计实现，系统可能单独连接 PostgreSQL 保存 `rejected` 日志。

## 5. 执行结果的三种状态

```text
安全策略未通过：rejected，不执行查询
查询正常完成：succeeded，进入 summarize，包括返回 0 行
查询超时或数据库报错：failed，写入 execution_error，进入 fail
```

## 6. 为什么节点和工具必须分开

如果节点直接包含 SQLGlot、数据库、事务和审计代码：

- 节点同时承担流程控制和底层实现，代码会迅速膨胀。
- 测试工作流时必须准备真实依赖，很难使用假工具。
- 更换数据库或安全实现时，工作流节点也要修改。
- 同一底层能力难以被 API 或其他工作流复用。

分开后，节点依赖稳定接口；测试时注入假工具，运行时注入真实适配器。

## 7. 当前边界

- SQL 校验工具已有真实 SQLGlot 实现。
- SQL 执行工具已有真实只读事务、超时和审计实现。
- 检索工具只有契约，没有真实 RAG。
- 尚未接入真实大模型。
- 当前工具不是 MCP。

## 8. 自测题

1. Node、工具契约、适配器和底层实现分别负责什么？
2. 为什么 `SQLValidationTool` 中的 `...` 不能完成校验？
3. `SQLGlotValidationTool` 最终调用哪个函数完成 SQL 安全检查？
4. 为什么执行工具同时接收 `original_sql` 和 `prepared_sql`？
5. `DELETE FROM orders` 被拒绝后，State 哪些字段变化？
6. `rejected`、`failed` 和 `succeeded` 有什么区别？
7. 为什么正常返回 0 行仍进入 `summarize`？
8. `source_id` 对可审计 Agent 有什么价值？
9. 当前工具为什么不是 MCP？
10. 当前测试为什么仍不能证明真实模型效果？

## 9. 自测题标准答案

### 1. Node、工具契约、适配器和底层实现分别负责什么？

Node 读取和更新 State、组织工作流；工具契约规定方法的输入输出；适配器把统一契约连接到现有代码；底层实现真正完成 SQLGlot 校验、数据库查询、事务和审计。

### 2. 为什么 `SQLValidationTool` 中的 `...` 不能完成校验？

`SQLValidationTool` 是 `Protocol`，`...` 只表示这里没有具体方法实现。它只规定校验工具必须拥有怎样的 `validate()` 方法，真正功能由符合该契约的实现类提供。

### 3. `SQLGlotValidationTool` 最终调用哪个函数完成 SQL 安全检查？

它先调用 `prepare_audited_sql()`，该函数再调用 `prepare_safe_sql()`。真正使用 SQLGlot 解析 AST、检查只读结构、访问白名单和强制行数限制的是 `prepare_safe_sql()`。

### 4. 为什么执行工具同时接收 `original_sql` 和 `prepared_sql`？

`original_sql` 用于审计模型最初生成了什么，`prepared_sql` 是经过安全校验和行数限制后真正交给 PostgreSQL 的版本。两者同时保存可以比较模型输出与实际执行内容。

### 5. `DELETE FROM orders` 被拒绝后，State 哪些字段变化？

`prepared_sql=None`、`sql_valid=False`、`sql_validation_error` 保存拒绝原因、`retry_count` 增加 1，`trace` 追加 `validate_sql`。`generated_sql` 仍保留原始 SQL。条件边随后选择重新生成或进入失败节点。

### 6. `rejected`、`failed` 和 `succeeded` 有什么区别？

`rejected` 表示安全策略未通过，业务查询没有执行；`failed` 表示查询已经开始，但因超时或数据库错误没有正常完成；`succeeded` 表示查询正常完成并产生结果集。

### 7. 为什么正常返回 0 行仍进入 `summarize`？

零行表示查询正常完成，只是没有记录符合条件。此时 `execution_error=None`、`query_rows=[]`，所以进入 `summarize`；超时或数据库错误才进入 `fail`。

### 8. `source_id` 对可审计 Agent 有什么价值？

`source_id` 表示检索内容来自哪个指标定义、Schema 或业务规则。它让系统能够解释 SQL 的生成依据，在结果有争议时回溯知识来源，并定位错误的业务定义。

### 9. 当前工具为什么不是 MCP？

当前工具是同一 Python 项目内部直接调用的接口和适配器，没有通过 MCP 协议对外提供服务。只有需要让外部 Agent、客户端或进程统一调用时，才有必要再增加 MCP 层。

### 10. 当前测试为什么仍不能证明真实模型效果？

测试使用固定输入和假工具，可以证明契约、State 更新、条件分支、错误转换以及现有 SQL/数据库适配器正确，但尚未调用真实大模型和真实 RAG，因此不能证明自然语言理解、检索质量和 SQL 生成质量。
