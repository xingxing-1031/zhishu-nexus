# W5-4 手机学习卡：故障注入与完整执行 Trace

## 1. 本阶段解决什么问题

W5-3 已经实现超时、重试、幂等和降级，但仅有机制还不够。系统还需要证明：每一种故障真的会走到预期分支，并且发生故障后能够准确定位。

W5-4 增加两项能力：

```text
故障注入：可控制地模拟真实故障
完整 Trace：记录请求内部每一步怎样运行
```

## 2. 什么是故障注入

故障注入是在测试环境主动让指定组件失败，例如：

```text
model.plan 第 1 次调用超时
model.generate_sql 返回 503
execute_sql 触发 statement_timeout
model.summarize 连续两次不可用
```

目的不是破坏生产系统，而是验证系统在预期故障下是否正确重试、拒绝、失败或降级。

## 3. 为什么不能随机失败

随机选择故障位置会产生不稳定测试：

- 同一份代码有时通过、有时失败。
- 无法区分预设故障和新代码缺陷。
- 失败后难以复现相同条件。
- 无法为每条路径规定准确预期结果。

当前使用 `ScriptedFaultInjector` 明确配置组件和第几次调用：

```text
component = model.plan
occurrence = 1
error = ConnectTimeout
```

## 4. 当前字符串 trace 的边界

原来的状态字段可能是：

```text
[plan, retrieve, generate_sql, validate_sql, execute_sql, summarize]
```

它适合前端显示“当前走到哪一步”，但不能说明：

- 每个节点耗时多少。
- 模型实际调用了几次。
- 第一次调用为什么失败。
- 重试等待了多久。
- 最终为什么降级。

因此旧字段继续保留，同时新增结构化执行事件。

## 5. 一个结构化 Trace 事件

每条事件至少包含：

```text
request_id
component
status
attempt
occurred_at
duration_ms
error_type
error_message
retry_delay_ms
```

第一次 503、等待后第二次成功可以记录为：

```text
model.plan attempt=1 started
model.plan attempt=1 failed error_type=HTTP_503
model.plan attempt=1 retry_scheduled retry_delay_ms=250
model.plan attempt=2 started
model.plan attempt=2 succeeded
```

## 6. Trace 状态

当前状态包括：

```text
started
succeeded
failed
retry_scheduled
rejected
pending
degraded
```

`rejected` 表示安全策略主动拒绝，例如非法 SQL；`failed` 表示允许开始处理，但执行过程中失败；`degraded` 表示核心可信结果存在，但非核心表达层未正常完成。

## 7. Trace 和审计日志的区别

审计日志回答业务与合规问题：

```text
谁提出请求
执行了什么 SQL
是否被拒绝
谁进行了审批
审批结果是什么
```

Trace 回答系统运行问题：

```text
经过哪些节点
每一步耗时多少
调用了几次模型
在哪次出现超时
为什么重试或降级
```

二者通过同一个 `request_id` 关联，但不能互相替代。

Trace 属于可观测性辅助能力。若 Trace 存储暂时不可用，系统应记录本地错误但不能因此把已经安全执行的核心分析改成失败；代价是该次 Trace 可能不完整，需要监控 Trace 写入失败率。

## 8. 总结失败的故障注入

若 SQL 已安全执行并返回真实 rows，再让总结模型失败，预期结果是：

```text
execute_sql = succeeded
model.summarize = failed
node.summarize = degraded
rows = 保留
错误自然语言 = 丢弃
result_status = degraded
```

如果注入的是 SQL 执行失败，就没有可信 rows，不能使用同一种降级策略。

## 9. Trace 的访问控制

Trace 可能包含错误信息、组件名称和内部执行细节，因此不能公开读取。

```text
请求本人 -> 可以查看
admin -> 可以查看
其他 analyst -> 403
不存在的 request_id -> 404
```

查询接口是：

```text
GET /analysis/{request_id}/trace
```

## 10. 当前代码位置

```text
fault_injection.py  确定性故障规则和上下文
tracing.py          Trace 模型、上下文、内存/数据库存储
model_adapters.py   记录模型每次尝试和重试等待
workflow.py         记录工作流节点开始和终态
analysis_service.py 建立请求 Trace 上下文和读取权限
app.py              Trace 查询接口
006_execution...    PostgreSQL Trace 表和索引
verify_w5_4.py      真实故障注入与 Trace 验收
```

## 11. 自测题

1. 故障注入为什么不能在生产环境随机触发？
2. 为什么故障规则需要指定组件和 occurrence？
3. 只记录最终 succeeded 会遗漏什么？
4. 模型第一次 503、第二次成功应记录哪些事件？
5. `rejected` 和 `failed` 有什么区别？
6. `failed` 和 `degraded` 有什么区别？
7. 为什么旧的字符串 trace 仍然保留？
8. Trace 和查询审计分别回答什么问题？
9. 为什么 Trace 与审计都需要 request_id？
10. 总结模型失败时为什么能够保留 rows？
11. SQL 执行失败时为什么不能返回估算表格？
12. 为什么 Trace 接口需要访问控制？
13. `duration_ms` 有什么用途？
14. `retry_delay_ms` 能帮助发现什么问题？

## 12. 自测题标准答案

1. 随机故障会影响真实用户和数据，也无法稳定复现；故障注入只应在受控测试环境使用。
2. 这样每次测试都在同一边界、同一次调用失败，输入和预期结果保持一致。
3. 会隐藏中间失败、重试次数、额外延迟、错误类型和系统依赖波动。
4. 第一次 started、failed、retry_scheduled，第二次 started、succeeded。
5. rejected 是策略判断不允许继续；failed 是允许执行后发生技术或资源错误。
6. failed 没有可信核心结果；degraded 已有可信核心结果，只是非核心能力未完成。
7. 它结构简单，现有 SSE、状态快照和前端进度仍可继续使用，避免一次改动破坏旧契约。
8. Trace 回答内部如何运行；查询审计回答谁执行了什么 SQL 以及结果状态。
9. 使用相同标识才能把用户请求、内部执行、查询和审批记录关联起来。
10. rows 已经通过证据、SQL 安全校验和 PostgreSQL 执行，失败的是表达层。
11. 没有真实数据库结果，估算数据可能误导业务人员。
12. Trace 包含内部组件、错误和耗时信息，其他用户不应读取。
13. 定位慢节点、计算端到端延迟并支持后续 p50/p95 分析。
14. 判断延迟来自实际调用还是退避等待，并发现服务是否长期依赖重试才能成功。
