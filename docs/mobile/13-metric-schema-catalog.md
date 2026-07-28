# W4-1 手机学习卡：指标字典与 Schema 目录

## 1. 本阶段解决什么问题

SQL 安全校验只能判断一条 SQL 是否允许执行，不能保证它采用了正确的业务口径。模型即使生成只读 SQL，也可能使用当前商品价格计算历史销售额、遗漏已支付条件或生成错误 JOIN。

W4-1 建立两个可版本化知识目录：

```text
MetricCatalog：指标含义、公式、来源、固定规则和支持维度
SchemaCatalog：表、字段、主键、JOIN 字段和一对多关系
```

指标字典提高业务正确性，SQLGlot 和数据库只读权限保证执行安全性。两者不能互相替代。

## 2. 指标定义包含什么

每个 `MetricDefinition` 包含：

```text
metric                 稳定英文指标编号
version                业务口径版本
display_name           中文显示名称
description            业务含义
formula                计算公式
source_tables          来源表
source_columns         来源字段
fixed_filters          指标自带规则
supported_dimensions   允许分组的维度
```

`sales_amount.v1` 的当前定义是：

```text
公式：SUM(order_items.quantity * order_items.unit_price)
固定规则：orders.status = 'paid'
来源：orders、order_items
维度：channel、product、category、day
```

历史销售额使用 `order_items.unit_price` 成交价快照，不使用 `products.unit_price` 当前参考价格。

## 3. 用户筛选与指标固定规则

用户说“只看淘宝”时，`channel = '淘宝'` 是用户筛选。用户只说“销售额”时，`orders.status = 'paid'` 仍会生效，因为它属于销售额指标定义中的固定规则。

```text
用户筛选：本次问题临时指定
固定规则：指标在所有查询中都必须遵守
```

## 4. 版本与来源编号

业务公式、固定筛选或支持维度发生变化时新增版本，不能覆盖旧定义：

```text
metric.sales_amount.v1 = 已支付成交金额
metric.sales_amount.v2 = 已支付成交金额 - 已完成退款金额
```

完整 `source_id` 同时保存指标和版本。它让审计记录能够说明当时依据了哪套公式，并支持历史结果复现。

同一个 `(metric, version)` 只能有一份定义。若两份不同公式都叫 `sales_amount.v1`，查询结果可能依赖读取顺序，审计也无法唯一回溯。

## 5. 为什么使用 `MetricCatalog.get()`

```python
catalog.get("sales_amount")
catalog.get("sales_amount", version="v1")
```

`definitions[0]` 只表示列表第一项，增加或调整指标顺序后可能静默读取错误指标。`get()` 按指标身份和版本选择定义，不存在时明确报错。

当前 `get()` 是精确目录查询，不是关键词或向量检索。W4-2 才会实现根据 `AnalysisPlan` 选择相关业务证据。

## 6. Schema 为什么必须记录 JOIN

只提供表和字段时，模型可能生成：

```sql
ON orders.order_id = order_items.product_id
```

它可能语法合法、只读安全，但业务关系错误。当前允许的关联是：

```text
orders.order_id = order_items.order_id
products.product_id = order_items.product_id
orders.order_id = refunds.order_id
```

`orders` 和 `products` 不能直接连接，必须经过 `order_items`。

## 7. 为什么记录一对多

一笔订单包含两条明细时，JOIN 后订单会出现两行：

```text
COUNT(*) = 2                 错误订单数
COUNT(DISTINCT order_id) = 1 正确订单数
```

连接后直接 `SUM(orders.amount)` 也会重复订单金额。销售额应从订单明细粒度计算：

```sql
SUM(order_items.quantity * order_items.unit_price)
```

一笔订单有 3 条明细和 2 条退款时，直接连接两张一对多表会得到 `3 × 2 = 6` 行。通常需要分别预聚合，不能依赖普通 `DISTINCT` 随意去重金额。

## 8. 指标定义不替代 SQL 安全

指标公式只是业务知识片段。模型仍要生成 SELECT、JOIN、WHERE、GROUP BY、ORDER BY 和 LIMIT，仍可能幻觉、遗漏规则或加入危险结构。

```text
指标字典：提供可信业务依据
模型输出：仍是不可信输入
SQLGlot：校验完整 SQL
白名单：限制表字段和函数
PostgreSQL 只读权限：最终兜底
```

## 9. 测试与真实验收

新增 6 项 Python 测试，证明指标和 Schema 目录的结构、版本、来源编号、主键和关联约束正确。它们不直接证明指标公式在真实数据上的结果正确。

真实公式验收使用固定种子数据执行手写 SQL：

```text
sales_amount.v1        = 32900
order_count.v1         = 5
units_sold.v1          = 12
refund_amount.v1       = 3500
refund_count.v1        = 6
average_order_value.v1 = 6580
```

PostgreSQL 输出：`W4-1 metric verification passed`。

这项数据库验收不需要大模型。真实模型评测用于证明模型能找到正确证据并生成正确 SQL，是后续另一个层面的验证。

## 10. 当前边界

- 已建立 6 个指标、4 张表和 3 条 JOIN 定义。
- 已能把定义转换为带 `source_id` 的 `RetrievalEvidence`。
- 尚未实现关键词、向量或混合检索。
- 尚未把真实检索工具装配进 LangGraph。
- 尚未接入真实大模型和端到端 SQL 生成。

## 11. 自测题

1. 指标字典和 SQL 安全校验分别解决什么问题？
2. 一个完整指标定义为什么需要公式、来源字段、固定筛选和支持维度？
3. 用户筛选和指标固定规则有什么区别？
4. 为什么指标定义必须保存版本？
5. `source_id="metric.sales_amount.v1"` 有什么价值？
6. 为什么不能用 `definitions[0]` 代替 `MetricCatalog.get()`？
7. 为什么同一个指标版本只能有一份定义？
8. Schema 为什么必须记录 JOIN 字段和连接路径？
9. 一对多关系怎样导致订单数和金额重复？
10. 3 条订单明细和 2 条退款直接连接为什么产生 6 行？
11. 指标公式已经由项目定义，完整 SQL 为什么仍需安全校验？
12. Python 目录测试与真实 PostgreSQL 指标验收分别证明什么？

## 12. 自测题标准答案

### 1. 指标字典和 SQL 安全校验分别解决什么问题？

指标字典在生成前提供业务含义、公式和数据来源，提高业务正确性；SQL 安全校验在生成后检查只读结构、访问范围和资源限制，防止不允许的 SQL 执行。

### 2. 一个完整指标定义为什么需要公式、来源字段、固定筛选和支持维度？

公式规定如何计算，来源字段规定从哪里取数，固定筛选规定哪些业务记录必须参与或排除，支持维度规定该指标允许怎样分组。缺少任一部分都可能得到语法正确但业务错误的 SQL。

### 3. 用户筛选和指标固定规则有什么区别？

用户筛选来自单次问题，例如只看淘宝；固定规则属于指标长期口径，例如销售额只统计已支付订单，即使用户没有说也必须生效。

### 4. 为什么指标定义必须保存版本？

业务口径会变化。保留版本可以区分新旧公式、解释结果变化、复现历史报告，并防止直接覆盖旧定义后失去审计依据。

### 5. `source_id="metric.sales_amount.v1"` 有什么价值？

它稳定标识一份具体指标和版本，让检索证据、SQL 生成依据、最终回答和审计记录能够回溯到唯一业务定义，不依赖可能变化的中文显示名称。

### 6. 为什么不能用 `definitions[0]` 代替 `MetricCatalog.get()`？

下标依赖列表顺序，新增或重排定义后可能静默读取错误指标。`get()` 按指标和版本准确选择，不存在时明确报错。

### 7. 为什么同一个指标版本只能有一份定义？

若两个不同公式拥有相同指标名和版本，系统无法判断哪一份是正式口径，结果可能依赖读取顺序，审计记录也无法唯一对应原始定义。

### 8. Schema 为什么必须记录 JOIN 字段和连接路径？

表字段只能说明有哪些数据，不能说明如何建立业务关系。错误 JOIN 可能返回零行、无关数据、笛卡尔积或重复金额，即使 SQL 语法合法且只读安全。

### 9. 一对多关系怎样导致订单数和金额重复？

一笔订单连接多条明细后会出现多行。`COUNT(*)` 会把明细行当作订单数，`SUM(orders.amount)` 会把同一订单金额重复相加。应按真实粒度使用去重计数、明细公式或预聚合。

### 10. 3 条订单明细和 2 条退款直接连接为什么产生 6 行？

同一订单下，每条明细都会分别匹配每条退款，因此形成 `3 × 2 = 6` 个组合，商品金额和退款金额都可能被重复聚合。

### 11. 指标公式已经由项目定义，完整 SQL 为什么仍需安全校验？

公式只是完整 SQL 的一部分。模型仍可能生成错误 JOIN、遗漏筛选、访问未授权字段或加入危险语句，因此所有模型输出都必须视为不可信输入并经过独立校验。

### 12. Python 目录测试与真实 PostgreSQL 指标验收分别证明什么？

Python 测试证明目录结构、版本、来源编号和关系约束符合代码契约；PostgreSQL 验收用固定种子数据执行公式 SQL并与人工标准答案比较，证明当前业务口径在真实数据库中的计算结果正确。两者都不能单独证明真实模型的检索和生成质量。
