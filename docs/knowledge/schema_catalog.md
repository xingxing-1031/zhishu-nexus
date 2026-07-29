# 零售 Schema 文档

## 表职责和字段

### `orders`

保存一次主订单的渠道、金额、状态和创建时间。

| 字段 | 类型 | 业务含义 |
|---|---|---|
| `order_id` | `TEXT` | 主键，订单唯一编号 |
| `channel` | `TEXT` | 销售渠道 |
| `amount` | `NUMERIC(12,2)` | 订单金额 |
| `status` | `TEXT` | `pending`、`paid`、`shipped`、`completed` 或 `cancelled` |
| `created_at` | `TIMESTAMPTZ` | 订单创建时间 |

### `products`

保存商品当前基础信息和参考价格。

| 字段 | 类型 | 业务含义 |
|---|---|---|
| `product_id` | `TEXT` | 主键，商品唯一编号 |
| `name` | `TEXT` | 商品名称 |
| `category` | `TEXT` | 商品类别 |
| `unit_price` | `NUMERIC(12,2)` | 当前参考价格，不代表历史成交价 |

### `order_items`

保存订单中的商品明细、购买数量和下单时的成交价快照。

| 字段 | 类型 | 业务含义 |
|---|---|---|
| `order_item_id` | `TEXT` | 主键，订单明细唯一编号 |
| `order_id` | `TEXT` | 外键，关联 `orders.order_id` |
| `product_id` | `TEXT` | 外键，关联 `products.product_id` |
| `quantity` | `INTEGER` | 购买数量 |
| `unit_price` | `NUMERIC(12,2)` | 下单时成交价快照 |

### `refunds`

保存订单退款事件。

| 字段 | 类型 | 业务含义 |
|---|---|---|
| `refund_id` | `TEXT` | 主键，退款唯一编号 |
| `order_id` | `TEXT` | 外键，关联原订单 |
| `refund_amount` | `NUMERIC(12,2)` | 退款金额 |
| `reason` | `TEXT` | 退款原因 |
| `status` | `TEXT` | `requested`、`approved`、`rejected` 或 `completed` |
| `created_at` | `TIMESTAMPTZ` | 退款创建时间 |

## 允许的关联

```sql
orders.order_id = order_items.order_id
products.product_id = order_items.product_id
orders.order_id = refunds.order_id
```

- 一个订单对应多条订单明细。
- 一个商品可以出现在多条订单明细中。
- 一个订单可以产生多条退款记录。
- `orders` 与 `products` 不直接连接，必须通过 `order_items`。

## 来源编号

```text
schema.orders
schema.products
schema.order_items
schema.refunds
schema.join.orders.order_items
schema.join.products.order_items
schema.join.orders.refunds
```

这些编号会进入 `RetrievalEvidence.source_id`，让生成的 SQL 能追溯到具体指标、表结构或关联规则。
