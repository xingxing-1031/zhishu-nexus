# 指标字典

这份文档是自然语言分析计划和 SQL 生成的业务依据。指标定义由版本化的 `MetricDefinition` 模型同步表达，后续检索结果使用 `source_id` 保存来源。

## `sales_amount.v1`

- **显示名称：** 销售额
- **业务含义：** 已支付订单中，订单明细成交价乘以购买数量后的总和。
- **公式：** `SUM(order_items.quantity * order_items.unit_price)`
- **来源表：** `orders`、`order_items`
- **来源字段：** `orders.status`、`order_items.quantity`、`order_items.unit_price`
- **固定规则：** `orders.status = 'paid'`
- **支持维度：** `channel`、`product`、`category`、`day`
- **来源编号：** `metric.sales_amount.v1`

销售额使用 `order_items.unit_price` 成交价快照，不使用 `products.unit_price` 当前参考价格。这样商品调价后，历史销售统计仍然保持稳定。

## `order_count.v1`

- **显示名称：** 订单数
- **业务含义：** 已支付订单的去重订单数量。
- **公式：** `COUNT(DISTINCT orders.order_id)`
- **来源表：** `orders`
- **固定规则：** `orders.status = 'paid'`
- **支持维度：** `channel`、`day`
- **来源编号：** `metric.order_count.v1`

## `units_sold.v1`

- **显示名称：** 销售件数
- **业务含义：** 已支付订单明细中的商品数量总和。
- **公式：** `SUM(order_items.quantity)`
- **来源表：** `orders`、`order_items`
- **固定规则：** `orders.status = 'paid'`
- **支持维度：** `channel`、`product`、`category`、`day`
- **来源编号：** `metric.units_sold.v1`

## `refund_amount.v1`

- **显示名称：** 退款金额
- **业务含义：** 退款记录中的退款金额总和，默认不排除某个退款状态。
- **公式：** `SUM(refunds.refund_amount)`
- **来源表：** `refunds`（按渠道时关联 `orders`）
- **支持维度：** `channel`、`refund_status`、`day`（通过 `orders.order_id = refunds.order_id` 关联渠道）
- **来源编号：** `metric.refund_amount.v1`

## `refund_count.v1`

- **显示名称：** 退款笔数
- **业务含义：** 退款记录的去重退款编号数量。
- **公式：** `COUNT(DISTINCT refunds.refund_id)`
- **来源表：** `refunds`（按渠道时关联 `orders`）
- **支持维度：** `channel`、`refund_status`、`day`（通过 `orders.order_id = refunds.order_id` 关联渠道）
- **来源编号：** `metric.refund_count.v1`

## `average_order_value.v1`

- **显示名称：** 平均订单金额
- **业务含义：** 已支付订单金额除以已支付去重订单数。
- **公式：** `SUM(orders.amount) / NULLIF(COUNT(DISTINCT orders.order_id), 0)`
- **来源表：** `orders`
- **固定规则：** `orders.status = 'paid'`
- **支持维度：** `channel`、`day`
- **来源编号：** `metric.average_order_value.v1`

## 版本规则

改变公式、固定筛选条件或支持维度时新增版本，不直接覆盖旧版本。例如退款扣除规则改变时，可以新增 `sales_amount.v2` 或使用更明确的 `net_sales_amount.v1`。旧版本保留用于历史报告复现和审计追踪。
