# 卡片 03：零售 ER 模型与核心 SQL

## 四张表分别做什么

- `orders`：一笔主订单的编号、渠道、状态、时间等信息。
- `products`：商品编号、名称、类别和当前参考价格。
- `order_items`：某笔订单里的某种商品、购买数量和下单时单价。
- `refunds`：关联订单的退款编号、金额、原因和状态。

订单和商品是多对多关系：一个订单可以买多个商品，一个商品也会出现在多个订单中。关系表 `order_items` 把它拆成两个一对多：

```text
orders 1 -> N order_items N <- 1 products
orders 1 -> N refunds
```

## 为什么明细保存 unit_price

`products.unit_price` 是当前参考价，以后可能变化；`order_items.unit_price` 是成交时的价格快照。财务和历史销售额必须按成交价计算，否则商品改价会篡改历史统计结果。

同一订单购买同一种商品 3 件，通常是一条明细，`quantity=3`。同一订单购买手机和耳机，则通常是两条明细。

## JOIN 在做什么

```sql
FROM orders AS o
JOIN order_items AS oi
  ON o.order_id = oi.order_id
```

`JOIN ... ON ...` 是连接写法：`JOIN` 指定连接哪张表，`ON` 指定两表哪两个字段代表同一业务关系。

`o.order_id = oi.product_id` 不成立，因为左边是订单编号，右边是商品编号，业务含义不同。字段都叫 ID 并不代表可以连接。

- 普通 `JOIN`（即 `INNER JOIN`）：只保留左右两边成功匹配的记录。
- `LEFT JOIN`：保留左表全部记录，右表没有匹配时对应字段为 `NULL`。

## SQL 查询顺序中的核心职责

```sql
SELECT channel, COUNT(*) AS paid_order_count
FROM orders
WHERE status = 'paid'
GROUP BY channel
HAVING COUNT(*) >= 10
ORDER BY paid_order_count DESC
LIMIT 5;
```

- `FROM`：从哪里取数据。
- `WHERE`：在分组前筛选原始行。
- `GROUP BY`：把相同渠道的行形成逻辑分组，不修改原表。
- `COUNT` / `SUM`：对分组计数或求和。
- `HAVING`：在聚合后筛选分组结果。
- `ORDER BY`：排序。
- `LIMIT`：限制最终返回行数。
- `AS`：给查询结果临时起别名，不会更改原表字段。

## 三个容易出错的点

### 1. 连接后订单重复

一笔订单有三条明细，连接后会出现三行。统计订单数时常用：

```sql
COUNT(DISTINCT o.order_id)
```

它按订单编号去重计数，避免把三条商品明细误认为三笔订单。

### 2. AND 与 OR 优先级

`AND` 的优先级高于 `OR`。业务条件复杂时使用括号明确意图：

```sql
WHERE status = 'paid'
  AND (channel = '淘宝' OR channel = '京东')
```

### 3. 空值不是零

`NULL` 表示未知或没有匹配值，不等于数字 0。展示退款总额时可以使用：

```sql
COALESCE(SUM(r.refund_amount), 0)
```

它只改变本次查询的显示结果，不修改数据库中的原始数据。

## 自测

### 1. 为什么不能总是读取商品表的当前价格计算历史订单？

<details>
<summary>展开标准答案</summary>

商品当前价格会变化。历史订单必须使用订单明细保存的成交价快照，否则改价后历史销售额和财务数据会随之变化。

</details>

### 2. 删除 `GROUP BY channel` 但仍在 `SELECT` 中保留 `channel` 和 `SUM(...)`，为什么可能报错？

<details>
<summary>展开标准答案</summary>

聚合函数把多行汇总成一个结果，但未分组的 `channel` 可能同时有淘宝、京东等多个值，数据库无法确定应该返回哪一个。可以保留 `GROUP BY channel` 做分渠道统计，或者同时删除 `channel` 得到全部渠道的总计。

</details>

### 3. `WHERE` 和 `HAVING` 的主要区别是什么？

<details>
<summary>展开标准答案</summary>

`WHERE` 在分组和聚合前筛选原始数据行；`HAVING` 在分组和聚合后筛选分组结果，例如只保留订单数大于 10 的渠道。

</details>

### 4. 为什么连接条件必须表达真实业务关系？

<details>
<summary>展开标准答案</summary>

连接条件决定两张表的哪些记录属于同一对象。订单编号只能与订单外键对应，商品编号只能与商品外键对应；错误连接即使语法能执行，也会生成没有业务意义的数据。

</details>

## 1 分钟口述

说明四张表的职责、`order_items` 为什么存在、成交价快照的作用，以及 `WHERE -> GROUP BY -> HAVING -> ORDER BY -> LIMIT` 的职责顺序。
