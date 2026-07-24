# LangGraph 的 State、Node 与 Edge

## W3-1 在做什么

前两周已经完成数据库、接口、SQL 安全和审计工具。从 W3 开始，需要把这些能力组织成一次可以追踪、分支和重试的 Agent 工作流。

W3-1 暂时不调用大模型。它先定义工作流的骨架：

```text
共享状态 State
+ 处理节点 Node
+ 节点连线 Edge
+ 条件路由 Conditional Edge
```

这样后续无论使用哪个模型，模型都只能在已经定义好的流程和状态边界中工作。

## State：一次任务的共享工作记录

`AnalysisState` 保存一次运营分析从开始到结束需要共享的数据，例如：

- 谁发起了请求：`request_id`、`user_id`
- 用户问了什么：`question`
- 最多返回多少行：`max_rows`
- 分析计划和检索证据：`plan`、`retrieved_context`
- 生成与校验的 SQL：`generated_sql`、`sql_valid`
- 查询结果和错误：`query_rows`、`execution_error`
- 最终回答：`final_answer`
- 重试控制：`retry_count`、`max_retries`
- 执行轨迹：`trace`

State 不是数据库，也不是模型自己的记忆。它是当前这一次 Agent 任务在节点之间传递的结构化数据。

```text
用户问题写入 State
-> 计划节点补充 plan
-> 检索节点补充 retrieved_context
-> SQL 节点补充 generated_sql
-> 执行节点补充 query_rows
-> 总结节点补充 final_answer
```

## Node：只负责一个步骤的函数

节点接收当前 State，并返回本节点负责更新的字段：

```python
def some_node(state: AnalysisState) -> dict[str, object]:
    return {"某个字段": "新的结果"}
```

当前图定义了七个节点职责：

1. `plan`：把用户问题整理成分析计划。
2. `retrieve`：检索指标定义和表结构证据。
3. `generate_sql`：根据计划和证据生成 SQL。
4. `validate_sql`：调用安全规则判断 SQL，并更新重试次数。
5. `execute_sql`：调用安全查询服务取得数据。
6. `summarize`：根据查询结果生成运营解释。
7. `fail`：统一整理无法继续的失败结果。

W3-1 测试使用的是假节点。假节点返回固定计划、SQL 和结果，用来验证图的顺序和分支，而不是验证大模型效果。真实计划模型会在 W3-2 实现，真实工具节点会在 W3-3 接入。

## 普通 Edge：顺序固定的连线

普通边表示一个节点完成后固定进入下一个节点：

```text
START
-> plan
-> retrieve
-> generate_sql
-> validate_sql
```

`summarize` 和 `fail` 完成后都会进入 `END`。

普通边不需要模型决定。工作流结构由 Python 代码固定，不能依赖提示词要求模型“记得下一步做什么”。

## Conditional Edge：根据 State 选择下一步

### SQL 校验后的分支

```text
sql_valid = true
-> execute_sql

sql_valid = false 且还有重试次数
-> generate_sql

sql_valid = false 且重试耗尽
-> fail
```

重试不是无限循环。`max_retries=2` 表示首次 SQL 失败后，最多再生成两次；每次校验失败都增加 `retry_count`。

### SQL 执行后的分支

```text
execution_error 有错误
-> fail

execution_error 没有错误
-> summarize
```

这里不能用“结果列表是否为空”判断成功。查询正常完成但返回 0 行仍然是成功，应进入 `summarize`，告诉用户没有符合条件的数据。只有超时或数据库报错才进入 `fail`。

## Trace 为什么需要 reducer

每个节点只追加自己的名称：

```text
plan 返回 ["plan"]
retrieve 返回 ["retrieve"]
generate_sql 返回 ["generate_sql"]
```

`trace` 使用列表加法 reducer，LangGraph 会把这些局部更新合并成：

```text
["plan", "retrieve", "generate_sql", ...]
```

如果没有 reducer，后一个节点可能直接覆盖前一个节点的轨迹。Reducer 规定多个节点更新同一字段时应该如何合并。

## 当前完整图

```text
START
  -> plan
  -> retrieve
  -> generate_sql
  -> validate_sql
       |-- 合法 -----------------> execute_sql
       |                             |-- 成功或 0 行 -> summarize -> END
       |                             `-- 执行错误 ----> fail ------> END
       |-- 非法且可重试 ----------> generate_sql
       `-- 非法且重试耗尽 --------> fail -----------> END
```

## 为什么现在不做多 Agent

当前所有节点共享同一个 `AnalysisState`，由同一张 LangGraph 图统一调度，所以它是单 Agent 的多节点工作流。

检索、SQL 校验和执行本身是工具节点，不需要被包装成拥有独立目标和历史的 Agent。只有以后评测证明某个步骤需要独立决策循环、独立工具权限和任务交接时，才有理由拆成多 Agent。

## 当前测试证明什么

W3-1 专项测试覆盖：

- 初始 State 字段完整。
- 成功路径按顺序经过六个节点。
- SQL 第一次失败后重新生成并成功。
- 重试耗尽后进入 `fail`。
- `max_retries=0` 时不重新生成。
- 数据库执行错误进入 `fail`。
- 正常返回 0 行仍进入 `summarize`。
- 路由函数读取明确的状态字段，而不是依赖结果真假。

这些测试证明工作流骨架和分支正确，不证明大模型已经接入，也不证明大模型生成 SQL 的质量。

## 当前边界

- 没有模型 API 和提示词。
- `plan` 仍是普通字典，W3-2 才会变成 Pydantic 结构化计划。
- 检索、安全校验和查询服务还没有接入真实节点，W3-3 才会封装工具契约。
- 没有 Checkpointer，中断恢复属于 W3-4。
- 没有拆成多 Agent。

## 自测

### 1. State 和数据库有什么区别？

<details>
<summary>查看答案</summary>

State 是单次 Agent 任务在节点间共享的结构化工作记录；数据库负责长期保存业务数据和审计数据。任务 State 可以包含数据库查询结果，但不等于数据库。

</details>

### 2. Node 为什么只返回部分字段？

<details>
<summary>查看答案</summary>

每个节点只负责一个步骤，只返回自己产生的更新；LangGraph 把更新合并回共享 State。这样节点职责清楚，也减少无关字段被意外覆盖。

</details>

### 3. 普通边和条件边有什么区别？

<details>
<summary>查看答案</summary>

普通边的下一节点固定；条件边读取 State 中的结构化字段，根据校验结果、错误或重试次数选择下一节点。

</details>

### 4. 为什么返回 0 行不能进入 fail？

<details>
<summary>查看答案</summary>

0 行可能只是没有数据满足筛选条件，查询本身已经正常完成。应进入总结节点说明“没有符合条件的数据”；只有超时或数据库错误才属于执行失败。

</details>

### 5. `max_retries=2` 表示什么？

<details>
<summary>查看答案</summary>

首次生成的 SQL 校验失败后，最多再回到 `generate_sql` 两次。达到上限仍不合法时进入失败节点，避免无限循环。

</details>

### 6. 为什么测试不需要真实大模型？

<details>
<summary>查看答案</summary>

W3-1 测试的对象是状态合并、节点顺序和条件路由。使用返回固定结果的假节点，可以让测试稳定、快速，并准确定位图结构错误。模型效果需要后续独立评测。

</details>

## 两分钟口述提纲

1. 为什么前两周的工具需要由工作流组织。
2. `AnalysisState` 保存什么，它和数据库有什么区别。
3. 七个节点分别负责什么。
4. 普通边与条件边的区别。
5. SQL 校验失败如何重试，为什么必须有限次。
6. 为什么 0 行仍是成功。
7. 当前没有模型、真实工具节点、Checkpointer 和多 Agent。
