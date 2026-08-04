# W5-2 手机学习卡：Human-in-the-loop 查询审批

## 1. 本阶段解决什么问题

W5-1 已经能直接拒绝写操作和角色越权，但有些查询在技术上合法、业务上仍然风险较高。例如 admin 读取退款原因，或者一次返回很多行数据。

W5-2 不把这类查询直接执行，也不把它当作非法 SQL，而是在数据库执行前暂停，等待可信人工审批。这就是 Human-in-the-loop，简称 HITL。

## 2. 三种处理结果

```text
普通合法查询 → 直接执行
合法但高风险查询 → 暂停并等待审批
写操作或角色越权 → 直接拒绝，不能审批放行
```

当前示例：

```text
analyst 查询渠道销售额 → 直接执行
analyst 查询 refunds.reason → 直接拒绝
admin 查询 refunds.reason → 等待审批
admin 执行 DELETE → 直接拒绝
```

HITL 不是让管理员绕过安全策略，而是在安全策略允许的只读范围内增加人工确认。

## 3. 为什么审批必须在 SQL 校验后

正确顺序是：

```text
生成 SQL
→ SQLGlot 安全校验
→ 形成 PreparedSQL
→ 风险评估
→ 必要时人工审批
→ 执行同一个 PreparedSQL
```

校验前的 SQL 可能包含写操作、非法表或越权字段，不能交给人工批准。数据库执行后再审批已经失去意义，因为风险行为已经发生。

## 4. 审批绑定什么

审批绑定已经校验并加上行数限制的 `PreparedSQL`，不是模糊的自然语言问题，也不是模型下一次可能重新生成的 SQL。

批准后工作流直接执行原 `PreparedSQL`。不能重新规划或生成，因为新 SQL 可能与人工看到和批准的内容不同。

人工拒绝后也不能让模型换一种写法继续尝试。人工拒绝表达的是本次查询不应执行，改写重试会让模型有机会绕过人的决定。

## 5. 当前风险规则

当前有两类合法查询需要审批：

- 引用敏感字段 `refunds.reason`。
- 最终允许返回的行数超过 100。

风险判断使用 `PreparedSQL.referenced_columns` 和 `PreparedSQL.result_limit`，不根据问题中的模糊关键词猜测。

如果请求上限是 500，但 SQL 自己明确写了 `LIMIT 10`，最终风险使用 10，不会因为请求上限而误判为大结果查询。

## 6. 两个新增节点

```text
assess_risk
→ 读取 PreparedSQL
→ 生成 QueryRisk
→ 普通查询路由到 execute_sql
→ 高风险查询记录 pending 并路由到 request_approval

request_approval
→ interrupt() 暂停
→ 接收可信审批结果
→ approved 路由到 execute_sql
→ rejected 路由到 fail
```

写操作和 analyst 越权在前面的 SQL 校验节点已经被拒绝，不会进入风险评估和审批节点。

## 7. interrupt 与 Command

`interrupt(payload)` 会暂停当前 LangGraph，并把审批所需的 SQL、风险原因和行数限制返回给调用端。

管理员审批后，服务使用：

```python
Command(resume={...})
```

恢复同一个线程。审批节点重新开始执行，但这次 `interrupt()` 返回人工决定，工作流才继续。

## 8. 为什么 interrupt 前不能做副作用

LangGraph 恢复动态中断时，会从审批节点开头重新执行。若在 `interrupt()` 前发送邮件、创建工单或写结果日志，恢复时这些操作可能再执行一次。

当前 pending 审计写在已经完成的 `assess_risk` 节点。`request_approval` 在 `interrupt()` 前不执行外部副作用，拿到恢复值后才写 approved 或 rejected。

仍然必须提前执行的外部操作，需要在 W5-3 增加幂等键和唯一约束。

## 9. 为什么服务重启后还能审批

请求的 `request_id` 同时作为 LangGraph `thread_id`。PostgreSQL Checkpointer 以它为索引保存完整 State：

```text
问题、计划、检索证据、生成 SQL、PreparedSQL
风险结果、审批状态、节点轨迹
```

服务重启或连接关闭后，前端提供原 `request_id`，新工作流实例就能找到快照。它不会重新调用模型，也不会重新生成 SQL。

## 10. HTTP 接口语义

```text
POST /analysis/run
普通查询完成 → 200 + AnalysisResponse
高风险查询暂停 → 202 + ApprovalRequiredResponse

GET /analysis/{request_id}
重新读取已持久化的 pending、成功或拒绝状态

POST /analysis/{request_id}/approval
可信 admin 提交 approve 或 reject
```

202 表示请求已接受但尚未完成，不能当成最终分析成功。前端应保存 `request_id` 并显示等待审批状态。

## 11. 谁可以审批

审批人身份来自可信 `AccessContext`，不是请求正文中的 `reviewer_id` 或 `role`。当前只有 admin 可以调用审批接口。

普通 analyst 调用审批接口返回 403。即使绕过 FastAPI 直接向工作流传入 analyst 审批信息，审批节点也会拒绝。

当前本地配置尚未实现真实登录和职责分离，因此生产环境仍需 JWT、企业身份系统和独立审批人策略。

## 12. 审批审计

新增 `query_approval_logs`，以事件方式记录：

```text
pending：查询进入等待审批
approved：谁批准了查询
rejected：谁拒绝以及拒绝原因
```

审批日志与查询执行日志分开。批准后还会产生查询 `succeeded/failed` 日志；人工拒绝不会产生数据库执行记录，因为查询没有执行。

## 13. 真实验证

- 完整自动化回归：`231 passed`。
- 第 004 迁移真实创建 `query_approval_logs`。
- admin 敏感查询暂停并写入 PostgreSQL Checkpointer。
- 关闭连接并重新连接后，批准请求恢复并真实返回 6 行退款原因。
- 拒绝请求进入 fail，没有进入 `execute_sql`。
- 审批日志真实记录 pending、approved 和 rejected。

## 14. 当前边界

- 风险策略目前只有一个敏感字段和 100 行阈值，后续需要配置化。
- 当前身份仍来自本地服务器配置，没有真实登录、JWT 和独立审批人。
- 尚未发送真实邮件或消息通知。
- 审批事件还没有幂等唯一键，进程在副作用与快照之间异常时可能重复记录，属于 W5-3。
- 写操作始终拒绝，不属于人工审批范围。

## 15. 自测题

1. HITL 解决的是什么问题？
2. 普通查询、高风险合法查询和非法查询分别怎样处理？
3. 为什么 admin 的 DELETE 不能通过审批放行？
4. 为什么审批必须放在 SQLGlot 校验之后？
5. 人工批准的对象为什么是 PreparedSQL？
6. 审批拒绝后为什么不能返回模型改写 SQL？
7. 当前哪两类查询需要审批？
8. 为什么风险判断使用最终 result_limit？
9. `assess_risk` 与 `request_approval` 分别负责什么？
10. `interrupt()` 和 `Command(resume=...)` 分别做什么？
11. 为什么不能在 interrupt 前发送审批通知？
12. 服务重启后怎样找到等待审批的工作流？
13. HTTP 202 表示什么？
14. 谁可以查看和处理审批？
15. 审批日志与查询日志为什么要分开？

## 16. 自测题标准答案

1. 对技术上合法但业务风险较高的只读查询，在执行前增加可信人工决定。
2. 普通合法查询直接执行；高风险合法查询暂停审批；写操作或越权查询直接拒绝。
3. Agent 的最高权限仍然是只读，人工审批不能突破系统的读写安全边界。
4. 校验前无法确定 SQL 是否只读、字段是否合法；人工只能审批已经通过确定性安全策略的查询。
5. PreparedSQL 已通过安全校验并确定了实际字段和 LIMIT，能够保证执行内容与人工看到的内容一致。
6. 拒绝表达本次查询不允许执行；让模型改写会使其可能绕过人工决定。
7. 引用 `refunds.reason`，或最终结果行数限制超过 100。
8. 请求上限可能是 500，但实际 SQL 只有 LIMIT 10；风险应依据真正可能返回的上限，避免误审批。
9. assess_risk 确定性计算风险并写 pending；request_approval 负责暂停、接收可信决定和路由。
10. interrupt 保存状态并暂停；Command(resume=...) 向同一线程提供人工结果并继续执行。
11. 恢复时节点从开头重跑，interrupt 前的外部副作用可能重复发生。
12. request_id 作为 thread_id，PostgreSQL Checkpointer 用它加载完整 State。
13. 请求已被接受但任务尚未完成，前端应显示 pending，而不是最终成功。
14. 请求本人可以查看自己的状态，admin 可以查看全部；只有可信 admin 可以处理审批。
15. 审批日志记录人工决策过程，查询日志记录数据库是否真正执行和结果，两者代表不同事实。
