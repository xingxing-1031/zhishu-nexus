# 安全查询的四道执行防线

## 这一阶段解决什么问题

W2-3 已经能使用 SQLGlot 判断一条 SQL 的结构是否只读，但“只读”不等于“可以安全执行”。下面这些语句都可能是 `SELECT`：

```sql
SELECT * FROM orders;
SELECT * FROM company_salary;
SELECT pg_sleep(60);
```

它们分别可能返回过多数据、访问未授权数据和长时间占用数据库。因此 W2-4 在 AST 只读校验之后增加表字段白名单、最大行数、数据库超时、只读事务和审计记录。

## 完整执行链路

```text
Agent 生成 SQL
-> SQLGlot 检查单语句和只读结构
-> 检查表、字段、Schema 和危险函数
-> 添加或压低 LIMIT
-> PostgreSQL 开启只读事务
-> 为当前事务设置 statement_timeout
-> 执行 SQL
-> 记录 succeeded / rejected / failed 审计事件
```

前半部分决定“是否允许尝试执行”，后半部分控制“执行时最多能消耗什么资源，并留下什么证据”。

## 第一道：表和字段白名单

当前只允许查询四张正式零售业务表：

- `orders`
- `products`
- `order_items`
- `refunds`

每张表还有各自允许的字段。例如 `orders` 只允许 `order_id`、`channel`、`amount`、`status` 和 `created_at`。

```sql
SELECT order_id, amount FROM orders;
```

可以通过；下面的语句会被拒绝：

```sql
SELECT secret_note FROM orders;
SELECT order_id FROM company_salary;
SELECT order_id FROM private.orders;
```

这是一种“默认拒绝”策略：没有明确批准的表、字段和 Schema 都不能访问。

### 为什么拒绝 `SELECT *`

`SELECT *` 会读取表中现在和未来的全部字段。以后表中如果加入手机号、地址等敏感字段，旧 SQL 会在没有修改的情况下自动读取它们。因此普通通配符被拒绝，查询必须明确列出字段。

`COUNT(*)` 不会返回每个字段，只用于统计行数，所以仍然允许：

```sql
SELECT channel, COUNT(*)
FROM orders
GROUP BY channel;
```

## 第二道：强制最大返回行数

运营问题通常不需要一次返回几十万条明细。`prepare_safe_sql()` 会根据本次请求的 `max_rows` 处理顶层 `LIMIT`：

- 没有 `LIMIT`：自动添加。
- 原有 `LIMIT` 更大：压低到 `max_rows`。
- 原有 `LIMIT` 更小：保留更严格的限制。

```text
原 SQL:  SELECT order_id FROM orders
执行 SQL: SELECT order_id FROM orders LIMIT 100

原 SQL:  SELECT order_id FROM orders LIMIT 500
max_rows: 20
执行 SQL: SELECT order_id FROM orders LIMIT 20
```

行数限制控制返回数据规模，但不能保证查询计算过程便宜。一个最终只返回 10 行的复杂 JOIN，也可能先处理大量中间数据，所以还需要超时。

## 第三道：只读事务和查询超时

执行服务在 PostgreSQL 中先执行：

```sql
SET TRANSACTION READ ONLY;
```

这让本次数据库事务只能读取，作为 AST 校验之外的第二层保护。随后使用 PostgreSQL 的 `statement_timeout` 限制本次查询时间。

例如设置为 2000 毫秒时，查询超过约 2 秒仍未结束，PostgreSQL 会主动取消它。超时不是让 Python 自己等待 2 秒后假装失败，而是让真正执行 SQL 的 PostgreSQL 停止查询。

当前允许的超时范围是 100 到 30000 毫秒，默认 2000 毫秒。范围限制可以防止超时值过小导致正常查询无法完成，也防止设置得过大而失去保护意义。

## 第四道：结构化审计

每次动态查询都会形成一条 `QueryAuditRecord`，主要记录：

- `request_id` 和 `user_id`
- 原始 SQL 和真正执行的 SQL
- 状态：`succeeded`、`rejected` 或 `failed`
- 拒绝或失败原因
- 返回行数
- 执行耗时

三种状态含义不同：

- `rejected`：安全策略没有通过，SQL 没有访问业务数据库。
- `failed`：策略已经通过，但 PostgreSQL 执行时超时或发生错误。
- `succeeded`：策略通过并成功取得结果。

审计不只是为了排错。它还能回答“谁在什么时候提交了什么查询、程序最终执行了什么、为什么被拒绝、返回了多少数据”。

## 为什么审计使用独立数据库连接

业务查询事务被设置成只读，不能在同一个事务中插入审计记录。另外，查询超时或数据库错误可能让当前事务进入失败状态，如果审计也放在这个事务中，审计记录会跟着回滚。

因此 `DatabaseAuditSink` 使用独立连接写入 `query_audit_logs`。业务查询失败时，审计记录仍然能够保留下来。

```text
只读查询连接 -> 执行业务 SELECT
独立审计连接 -> 写入 query_audit_logs
```

## 代码分别放在哪里

- `sql_safety.py`：表字段白名单、危险函数检查和强制 `LIMIT`。
- `query_service.py`：只读事务、超时、执行和三种审计状态。
- `audit.py`：审计模型与数据库审计写入器。
- `002_query_audit_logs.sql`：创建真实审计表和索引。
- `verify_w2_4.py`：连接真实 PostgreSQL 验证成功与拒绝记录。

## 当前边界

当前安全执行服务已经可以独立运行和测试，但还没有连接自然语言模型或 Agent 工作流。表字段规则目前直接写在 Python 中，后续可以来自带版本的 Schema/指标目录。当前使用事务级只读保护，生产环境还应使用独立的 PostgreSQL 只读账号。

危险函数规则也不是整个安全体系。即使语法、白名单、行数和超时都通过，仍然需要角色权限、敏感字段分级、人工确认和完整 Agent Trace。

## 自测

### 1. 为什么 W2-3 通过后仍然需要 W2-4？

<details>
<summary>查看答案</summary>

W2-3 主要确认 SQL 是单条只读结构，不能控制它访问哪些业务数据、返回多少行、运行多久，也没有留下执行证据。W2-4 补上数据范围、资源范围和审计边界。

</details>

### 2. 为什么 `SELECT * FROM orders` 会被拒绝，但 `COUNT(*)` 可以？

<details>
<summary>查看答案</summary>

普通 `SELECT *` 会返回当前及未来加入的全部字段，可能扩大数据暴露范围；`COUNT(*)` 只统计行数，不返回每个字段的值。

</details>

### 3. `LIMIT 10` 能不能代替查询超时？

<details>
<summary>查看答案</summary>

不能。`LIMIT` 限制最终返回行数，但数据库在得到这 10 行前仍可能执行复杂 JOIN、排序或聚合。超时限制的是查询占用数据库的时间。

</details>

### 4. `rejected` 和 `failed` 有什么区别？

<details>
<summary>查看答案</summary>

`rejected` 表示安全策略未通过，业务 SQL 没有执行；`failed` 表示策略通过并尝试执行，但数据库发生超时或其他错误。

</details>

### 5. 为什么审计不能直接写入同一个只读事务？

<details>
<summary>查看答案</summary>

只读事务不能插入审计数据；查询失败时同一事务还可能回滚或进入错误状态。独立审计连接可以让失败查询的证据仍被保存。

</details>

## 两分钟口述提纲

1. 只读 SQL 为什么仍可能危险。
2. 表字段白名单和 `SELECT *` 的风险。
3. 强制 `LIMIT` 与查询超时分别控制什么。
4. PostgreSQL 只读事务提供了什么第二层保护。
5. 三种审计状态和独立审计连接的原因。
6. 当前还没有接入 Agent，也没有替代生产只读账号和角色权限。
