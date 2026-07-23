# 卡片 07：SQLGlot 与只读 SQL AST 校验

## 本阶段要掌握什么

W2-3 的目标是：在 SQL 交给 PostgreSQL 执行之前，先确认它是一条允许的只读查询。

不要求背 SQLGlot 的全部 API。需要理解：

1. AST 是什么，为什么比字符串搜索可靠。
2. 为什么要检查语句数量、根节点和整棵树。
3. 当前校验允许什么、拒绝什么。
4. SQL AST 校验不能替代数据库权限、超时和结果行数限制。

## AST 是什么

AST 是 Abstract Syntax Tree，即“抽象语法树”。SQLGlot 会把 SQL 字符串解析成有层次的结构节点。

例如：

```sql
SELECT channel, COUNT(*) FROM orders GROUP BY channel
```

不会只被当成一段文字，而会被解析成大致这样的结构：

```text
Select
├── Column(channel)
├── Count
├── From(orders)
└── Group(Column(channel))
```

程序可以直接检查根节点是 `Select`，以及树中是否出现 `Delete`、`Insert`、`Drop` 等危险节点。

AST 只负责解析和检查，不连接数据库，也不执行 SQL。

## 为什么不能只搜索字符串

简单做法可能是：

```python
if "delete" in sql.lower():
    reject()
```

这种方法不可靠：

- SQL 可能包含多余空格、注释或不同写法。
- 危险操作可能藏在 CTE 内部。
- 字符串中出现 `delete` 可能只是列名、注释或文本值。
- 字符串检查无法准确判断语句边界和 SQL 语法结构。

SQLGlot 解析后，程序检查的是节点类型和树结构，不是猜测文字含义。

## 当前校验的五个步骤

`validate_read_only_sql()` 的流程是：

```text
1. 拒绝空字符串
2. 按 PostgreSQL 方言解析 SQL
3. 要求只能解析出一条语句
4. 要求根节点属于只读查询类型
5. 扫描整棵 AST，拒绝写入、DDL 和 SELECT INTO 节点
```

### 1. 空 SQL

空输入没有任何查询意义，直接拒绝。

### 2. PostgreSQL 方言解析

项目数据库是 PostgreSQL，因此解析时使用 `read="postgres"`。不同数据库的 SQL 语法可能不同，方言必须明确。

### 3. 只允许一条语句

下面的 SQL 不能通过：

```sql
SELECT 1;
DROP TABLE orders;
```

即使第一条是 SELECT，第二条仍然会执行危险操作。只允许一条语句可以先挡住这种多语句输入。

### 4. 检查根节点

当前允许的根节点是：

- `Select`
- `Union`
- `Intersect`
- `Except`

这些表示查询或查询集合。`Delete`、`Update`、`Insert`、`Create`、`Drop` 等根节点会被拒绝。

### 5. 扫描整棵树

只检查根节点还不够。例如：

```sql
WITH deleted AS (
    DELETE FROM orders RETURNING *
)
SELECT * FROM deleted;
```

它的根节点可能是 `Select`，但内部包含 `Delete`。所以程序还要遍历整棵 AST，发现 `Delete`、`Insert`、`Update`、`Merge`、`Create`、`Drop`、`Alter`、`TruncateTable` 或 `Into` 就拒绝。

`SELECT ... INTO ...` 也不能通过，因为它会把查询结果写入新表。

## 当前代码的职责

`sql_safety.py` 只负责：

- 调用 SQLGlot 解析 SQL。
- 判断是否只有一条语句。
- 判断是否属于只读查询。
- 抛出统一的 `SQLSafetyError`。

它当前还没有负责：

- 数据库账号权限。
- 表和字段白名单。
- 查询超时。
- 返回行数限制。
- 危险函数或敏感字段检查。
- 审计日志。

这些属于后续 W2-4 和更后的安全查询服务。

## SQL AST 校验和参数化 SQL的区别

两者解决的问题不同：

| 机制 | 主要作用 |
|---|---|
| 参数化 SQL | 防止用户输入改变 SQL 结构，降低注入风险 |
| AST 校验 | 判断 SQL 结构是否属于允许的只读查询 |
| 数据库权限 | 从数据库账号层面阻止写入 |
| 超时和行数限制 | 控制查询资源消耗 |

可靠的查询服务需要多层防护，不能认为 SQLGlot 通过就代表所有安全问题已经解决。

## 自测

### 1. 为什么 AST 比 `"delete" in sql.lower()` 更可靠？

<details>
<summary>展开标准答案</summary>

AST 检查的是 SQL 的语法节点和层次结构，可以区分真正的 `Delete` 节点、注释、文本值和字段名称，也能发现隐藏在 CTE 中的写操作。字符串搜索只是在猜文字，无法准确判断 SQL 结构和语句边界。

</details>

### 2. 为什么要同时检查根节点和整棵 AST？

<details>
<summary>展开标准答案</summary>

根节点检查可以快速判断顶层是否是 SELECT 查询，但写操作可能藏在 CTE 或子结构中。遍历整棵 AST 可以发现内部的 Delete、Insert、Into 等危险节点，两层检查结合才能避免只看外层造成绕过。

</details>

### 3. `SELECT 1; DROP TABLE orders` 为什么必须拒绝？

<details>
<summary>展开标准答案</summary>

它包含两条语句，第一条虽然是只读 SELECT，第二条却是 DROP。只允许一条语句可以直接拒绝这种混合输入，避免后面的危险语句被执行。

</details>

### 4. SQLGlot 校验通过后，是否可以直接认为查询绝对安全？

<details>
<summary>展开标准答案</summary>

不可以。当前 AST 校验主要判断语句类型和明显写操作，还没有覆盖危险函数、敏感字段、表字段白名单、超时、行数限制和数据库权限。它是安全查询链路的一层，不是全部安全措施。

</details>

### 5. SQLGlot 会不会执行 SQL？

<details>
<summary>展开标准答案</summary>

不会。SQLGlot 只解析 SQL 并生成 AST；只有后续代码把通过校验的 SQL 交给 psycopg 和 PostgreSQL 时，数据库才会真正执行查询。

</details>

## 口述参考结构

用约 2 分钟说明：AST 的定义、字符串检查的缺陷、五步校验流程、CTE 隐藏 Delete 的例子、参数化 SQL 与 AST 校验的区别，以及当前尚未覆盖的权限/超时/行数限制。

本阶段通过标准：能说明“解析和执行是两回事”，能解释为什么检查整棵树，并且不会把 SQLGlot 校验说成完整安全方案。
