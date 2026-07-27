# W3-4 手机学习卡：PostgreSQL Checkpointer 与中断恢复

## 1. 本阶段解决什么问题

没有 Checkpointer 时，`AnalysisState` 只存在于当前 Python 进程的内存中。程序关闭或进程崩溃后，已经完成的计划、检索、SQL 生成和校验结果都会丢失，任务只能从头运行。

W3-4 使用 PostgreSQL Checkpointer 持久化 LangGraph 的工作流检查点，使同一个任务能够在程序重新连接数据库后继续执行。

```text
第一次运行
-> 完成 plan、retrieve、generate_sql、validate_sql
-> 在 execute_sql 前暂停
-> State 和下一节点位置写入 PostgreSQL

恢复运行
-> 使用相同 thread_id 查找检查点
-> 读取原 State
-> 从 execute_sql 继续
```

## 2. State、Checkpoint 和 Checkpointer

```text
AnalysisState：单次分析任务当前的结构化工作记录
Checkpoint：某个节点边界上的 State 快照和恢复元数据
Checkpointer：负责保存和读取 Checkpoint 的组件
PostgreSQL：当前 Checkpointer 使用的持久化存储
```

Checkpoint 不是普通日志。它不仅记录“执行过什么”，还保存恢复工作流所需的 State、节点位置和版本信息。

## 3. Checkpoint 与其他数据的区别

| 数据 | 作用 |
|---|---|
| `orders`、`products` 等业务表 | 保存零售业务事实 |
| 查询审计日志 | 记录谁执行了什么 SQL、结果是成功、拒绝还是失败 |
| LangGraph Checkpoint | 保存某个 Agent 任务执行到哪里以及当时的 State |
| 数据库备份 | 用于数据库整体灾难恢复 |

Checkpointer 不能代替业务表、查询审计、数据库备份或外部副作用的幂等控制。

## 4. `setup()` 在做什么

```python
checkpointer.setup()
```

`setup()` 创建或升级 LangGraph 自己管理的检查点表。它不创建也不修改 `orders`、`products`、`order_items` 和 `refunds` 等业务表。

```text
业务迁移 -> 创建零售业务表
checkpointer.setup() -> 创建 LangGraph 存档表
工作流运行 -> 把真正的检查点写入存档表
```

因此，`setup()` 是准备“存档系统”，不是它自己产生业务任务的快照。没有运行 `setup()` 时，PostgresSaver 可能因为检查点表不存在而无法保存和恢复 State。

## 5. `thread_id` 为什么重要

`thread_id` 是 Checkpointer 查找同一条工作流历史的隔离键。当前单次分析场景使用稳定且唯一的 `request_id` 作为 `thread_id`。

```python
config = {
    "configurable": {
        "thread_id": "request-001",
    }
}
```

- 新分析请求：使用新的 `request_id` 和新的初始 State。
- 恢复旧任务：继续使用原来的 `request_id`。
- 不能只使用 `user_id`：同一个用户可以同时发起多个独立请求。

两个任务误用同一个 `thread_id` 不一定立即报错，更危险的是 State 被错误读取或合并，导致继承另一个任务的计划、SQL、结果、重试次数或下一节点位置。

## 6. 第一次运行与恢复运行

第一次运行需要提交初始 State：

```python
graph.invoke(initial_state, config)
```

恢复时不再提交新输入：

```python
graph.invoke(None, config)
```

这里各部分的含义是：

```text
graph：已经组装好的 LangGraph 工作流
invoke：启动或继续运行工作流
None：本次没有新的初始输入
config：通过 thread_id 指定要恢复哪一个任务
```

重新传入 `create_initial_state(...)` 相当于向已有线程再次提交初始输入，可能覆盖或合并旧字段、重复追加 `trace`，并让入口处的模型节点重新执行。真正的新请求应该使用新 State 和新 `thread_id`。

## 7. 为什么连接必须保持打开

```python
with open_postgres_checkpointer() as checkpointer:
    graph = build_analysis_graph(checkpointer=checkpointer)
    graph.invoke(initial_state, config)
```

`with` 管理数据库连接的生命周期：

```text
进入 with -> 打开连接
缩进内部 -> Checkpointer 可以读取和写入检查点
离开 with -> 自动关闭连接
```

如果在 `with` 内返回 Checkpointer，Python 会在函数真正返回前先退出 `with` 并关闭连接。调用者虽然仍能拿到 Checkpointer 对象，但它引用的是已关闭连接，后续读取或保存检查点通常会直接报数据库连接错误。

`return` 本身不是特殊的关闭命令；真正触发关闭的是执行 `return` 时离开了 `with` 作用域。

## 8. 暂停边界与幂等

当前验收使用 `interrupt_before="execute_sql"`，在执行节点开始前建立稳定的暂停边界。它能证明关闭第一条 PostgreSQL 连接后，第二条连接可以使用相同 `thread_id` 从待执行节点继续。

但它不等于“进程在节点执行到一半时突然崩溃”。如果节点中途崩溃，节点完成后的检查点还没有产生，恢复时可能从上一个检查点重新执行该节点。

因此，涉及以下外部副作用的节点仍需要幂等保护：

- 数据库写入
- 发送消息或邮件
- 扣款或创建订单
- 调用会产生真实资源的外部 API

## 9. 序列化为什么需要稳定类型

Checkpoint 要把 Pydantic 模型、检索证据和 `PreparedSQL` 等 Python 对象写入 PostgreSQL，并在恢复时还原为原来的类型。

项目使用显式类型允许列表，只允许恢复当前 State 中已知的模型类型。`PreparedSQL` 改成冻结的 Pydantic 模型后，恢复时会重新校验字段类型，避免元组经过 msgpack 后变成普通列表而破坏类型契约。

## 10. 当前测试证明了什么

- 相同 `thread_id` 可以恢复原任务。
- 不同 `thread_id` 的 State 相互隔离。
- 恢复时不会重复执行已经完成的节点。
- PostgreSQL 连接关闭后重新建立连接，仍能读取持久化检查点。
- 已注册的 State 模型可以安全序列化和恢复。

仍然不能证明：

- 真实大模型生成计划和 SQL 的质量。
- 真实 RAG 检索质量。
- 节点中途强制崩溃时所有外部副作用都不会重复。

## 11. 自测题

1. `AnalysisState`、Checkpoint 和 Checkpointer 分别是什么？
2. 没有 Checkpointer 时，程序关闭后为什么不能继续原任务？
3. `thread_id` 的作用是什么，为什么不能只使用 `user_id`？
4. 为什么恢复时使用 `graph.invoke(None, config)`？
5. 新请求与恢复旧请求分别应该怎样选择 State 和 `thread_id`？
6. `with open_postgres_checkpointer()` 在管理什么？
7. 为什么不能在数据库连接的 `with` 结束后继续使用返回的 Checkpointer？
8. `checkpointer.setup()` 与真正保存 Checkpoint 有什么区别？
9. `interrupt_before` 的测试为什么不能证明节点中途崩溃也绝不重复执行？
10. Checkpoint、业务表和查询审计日志为什么不能互相替代？
11. 为什么外部副作用仍然需要幂等设计？
12. 当前 W3-4 测试还不能证明什么？

## 12. 自测题标准答案

### 1. `AnalysisState`、Checkpoint 和 Checkpointer 分别是什么？

`AnalysisState` 是单次分析任务当前的结构化工作记录；Checkpoint 是某个节点边界上的 State 快照和恢复元数据；Checkpointer 是负责把 Checkpoint 写入持久化存储并按 `thread_id` 读取它的组件。

### 2. 没有 Checkpointer 时，程序关闭后为什么不能继续原任务？

State 只存在于当前 Python 进程内存中。进程结束后数据和执行位置都会丢失，没有持久化检查点就无法找回已完成步骤，只能重新运行任务。

### 3. `thread_id` 的作用是什么，为什么不能只使用 `user_id`？

`thread_id` 是查找和隔离一条工作流历史的键。同一个用户可以发起多个独立请求，所以 `user_id` 不能唯一标识任务；当前使用唯一且稳定的 `request_id` 作为 `thread_id`。

### 4. 为什么恢复时使用 `graph.invoke(None, config)`？

`None` 表示本次没有新输入，LangGraph 应根据 `config` 中相同的 `thread_id` 读取最近检查点并执行待处理节点。重新传入初始 State 会变成向旧线程提交新输入，可能覆盖或合并旧状态并重跑入口模型节点。

### 5. 新请求与恢复旧请求分别应该怎样选择 State 和 `thread_id`？

新请求使用新的初始 State 和新的唯一 `thread_id`；恢复旧请求不提交新 State，继续使用原来的 `thread_id`。

### 6. `with open_postgres_checkpointer()` 在管理什么？

它管理 PostgreSQL Checkpointer 连接的生命周期。进入 `with` 时打开并初始化连接，缩进内部保持连接可用，离开 `with` 时即使发生异常也会自动关闭连接。

### 7. 为什么不能在数据库连接的 `with` 结束后继续使用返回的 Checkpointer？

返回对象仍然存在，但它内部引用的数据库连接已经在退出 `with` 时关闭。后续读取或写入检查点时通常会发生连接已关闭的错误。

### 8. `checkpointer.setup()` 与真正保存 Checkpoint 有什么区别？

`setup()` 只创建或升级 LangGraph 保存检查点所需的内部表，相当于准备存档系统；工作流运行到节点边界时，Checkpointer 才会把具体任务的 State 和恢复元数据写入这些表，形成真正的 Checkpoint。

### 9. `interrupt_before` 的测试为什么不能证明节点中途崩溃也绝不重复执行？

`interrupt_before` 在节点开始前建立确定的暂停边界，最近检查点已经明确记录下一节点。节点中途崩溃时尚未产生节点完成后的新检查点，恢复可能从上一个检查点重新执行该节点。

### 10. Checkpoint、业务表和查询审计日志为什么不能互相替代？

业务表保存订单和商品等业务事实；审计日志记录谁执行了什么查询以及结果状态；Checkpoint 保存某个 Agent 任务的 State 和执行位置。三者的数据对象、生命周期和恢复目标不同。

### 11. 为什么外部副作用仍然需要幂等设计？

Checkpointer 只能恢复到最近完成的检查点，不能保证中途崩溃节点内已经发生的写入、发消息或外部 API 调用没有成功。节点重跑可能重复产生副作用，因此需要业务唯一键、幂等键或去重机制。

### 12. 当前 W3-4 测试还不能证明什么？

它不能证明真实大模型和真实 RAG 的质量，也不能证明所有节点中途强制崩溃和外部系统故障下都不会重复副作用。当前证明的是工作流 State 可以通过 PostgreSQL 持久化、隔离并跨连接恢复。
