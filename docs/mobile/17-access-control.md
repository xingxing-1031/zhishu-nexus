# W5-1 手机学习卡：可信身份与字段访问控制

## 1. 本阶段解决什么问题

W4-4 已能把自然语言变成安全只读 SQL，但“SQL 是只读的”不等于“每个用户都可以读取所有字段”。W5-1 增加第二层边界：根据可信角色控制可读取字段。

当前规则是：

```text
analyst：可做普通经营分析，但不能读取 refunds.reason
admin：可以读取 refunds.reason
两种角色：都只能执行只读查询
```

`admin` 表示更高的数据读取范围，不表示数据库写权限。

## 2. 为什么不能相信请求中的 role

如果客户端可以发送：

```json
{"user_id": "USER-001", "role": "admin"}
```

并由后端直接相信，那么任何用户都可以把自己的角色改成管理员。这叫越权或权限提升。

因此当前开发阶段由服务器配置生成 `AccessContext`：

```text
AccessContext = 可信 user_id + 可信 role
```

客户端仍提交 `user_id` 作为请求业务字段，但它必须与可信上下文一致，否则 FastAPI 在工作流启动前返回 403。

## 3. 认证与授权的区别

认证回答“你是谁”，授权回答“你可以做什么”。

当前 W5-1 还没有登录、密码、JWT 或企业单点登录。它只是用服务器环境配置模拟一个可信身份，以便先完成授权链路。未来接入真实认证后，`AccessContext` 应由经过验证的令牌或会话产生，而不是由请求正文产生。

## 4. 权限怎样进入完整工作流

```text
服务器配置
→ get_access_context
→ AccessContext(user_id, role)
→ FastAPI 检查请求 user_id
→ AnalysisState 保存 access_role
→ SQL 生成提示包含角色和禁用字段
→ SQLGlot AST 字段策略再次强制校验
→ 合法 PreparedSQL 保存 access_role
→ PostgreSQL 只读执行或在执行前拒绝
```

角色写入 State 后，每个后续节点看到的是同一个可信角色，不需要相信模型或客户端重新声明权限。

## 5. 为什么提示词和代码校验都需要

SQL 生成模型会收到：

```text
access_role = analyst
forbidden_columns = [refunds.reason]
```

这能减少模型生成越权 SQL，降低失败和重试成本，但提示词不是安全边界。模型仍可能忽略、误解或被输入诱导。

真正的兜底是代码：SQLGlot 把 SQL 解析为 AST，字段策略遍历列引用，再根据角色拒绝 `refunds.reason`。即使模型生成了越权 SQL，也不会连接 PostgreSQL 执行。

## 6. 为什么要检查别名和 CTE

同一个敏感字段可以写成不同形式：

```sql
SELECT reason FROM refunds;
SELECT r.reason FROM refunds AS r;
WITH x AS (SELECT reason FROM refunds) SELECT reason FROM x;
```

只搜索字符串容易漏掉别名、大小写和嵌套结构。AST 校验会识别真实的表、别名和列引用，因此三种写法对 `analyst` 都会被拒绝。

## 7. admin 为什么仍不能 DELETE

权限控制有多个相互独立的维度：

```text
读写权限：本 Agent 始终只读
表权限：只能读取批准的四张业务表
字段权限：不同角色可读字段不同
资源权限：仍受 LIMIT 和 statement_timeout 限制
```

`admin` 只放宽字段权限，没有绕过只读根节点和危险操作检查。因此 `DELETE`、`UPDATE`、`INSERT` 和 DDL 对 admin 仍然非法。

## 8. 403、rejected 和 failed 的区别

- `403`：HTTP 身份不匹配，请求在工作流启动前被拒绝。
- `rejected`：请求进入安全策略，但 SQL 不符合权限或只读规则，数据库没有执行该 SQL。
- `failed`：安全校验已经通过并开始查询，但数据库连接、超时或执行过程失败。

权限越权属于 `rejected`，不是 `failed`。

## 9. 为什么 PreparedSQL 保存角色

`PreparedSQL` 是安全校验后的执行凭证。保存 `access_role` 可以说明这条 SQL 是按照哪个角色校验的，也能随 Checkpointer 一起恢复，避免审计和恢复时丢失权限上下文。

它不能代替执行前校验，也不能让外部用户自行构造后直接执行；它只是内部工作流中的受校验对象。

## 10. 真实验证结果

自动化回归：`209 passed`。

真实 PostgreSQL 验收：

```text
analyst + SELECT reason FROM refunds
→ rejected，未执行，审计记录包含 refunds.reason

admin + SELECT reason FROM refunds
→ succeeded，返回 6 行种子数据

admin + DELETE FROM orders
→ rejected，未执行，订单数据没有被修改
```

## 11. 当前边界

当前 `AccessContext` 来自服务器环境配置，只适合开发和演示。尚未实现真实登录、JWT、密码哈希、多租户行级权限、PostgreSQL 独立只读账号和企业权限系统。

W5-1 证明的是可信角色能贯穿接口、State、模型输入、安全校验、审计和恢复，不代表已经完成生产认证授权系统。

## 12. 自测题

1. 为什么请求正文中的 `role=admin` 不能直接信任？
2. `AccessContext` 当前包含什么，来自哪里？
3. 认证和授权分别回答什么问题？
4. 请求 `user_id` 与可信上下文不一致时发生什么？
5. 为什么角色要写入 `AnalysisState`？
6. 为什么还要把禁用字段告诉 SQL 生成模型？
7. 为什么提示词不能代替 AST 权限校验？
8. analyst 与 admin 当前的权限差异是什么？
9. admin 为什么仍不能执行 `DELETE`？
10. 为什么别名和 CTE 也必须测试？
11. `403`、`rejected`、`failed` 分别表示什么？
12. 真实验收证明了什么，尚未证明什么？

## 13. 自测题标准答案

1. 客户端可自行修改请求内容；直接信任会让普通用户把自己提升为管理员。
2. 包含可信 `user_id` 和 `role`；当前由服务器环境配置产生，未来应由真实认证结果产生。
3. 认证回答用户是谁，授权回答该身份可以访问哪些资源和执行哪些操作。
4. FastAPI 在工作流启动前返回 403，Runner 不会被调用。
5. 让后续 SQL 生成、校验、审计和恢复使用同一个可信角色，避免各节点重新相信外部输入。
6. 让模型尽量首次生成合规 SQL，减少拒绝、重试和模型调用成本。
7. 提示词只是模型输入，模型可能忽略或误解；AST 代码策略才会确定性拒绝越权列。
8. admin 可以读取 `refunds.reason`，analyst 不可以；其他当前规则相同。
9. admin 只放宽字段读取范围，没有获得写权限；Agent 的 SQL 根节点和危险操作策略始终只允许读取。
10. 敏感字段可通过表别名或嵌套查询出现；只测直接写法无法证明不存在结构绕过。
11. 403 是可信身份不匹配；rejected 是执行前策略拒绝；failed 是通过策略后数据库执行失败。
12. 证明角色能贯穿当前链路并在真实 PostgreSQL 前正确拒绝或放行；尚未证明登录、JWT、多租户和生产数据库权限已经完成。
