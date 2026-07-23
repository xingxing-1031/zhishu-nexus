from retail_analytics_agent.database import DatabaseConnection
from retail_analytics_agent.models import (
    ChannelSalesSummary,
    OrderStatusSummary,
    ProductSalesSummary,
    RefundStatusSummary,
)


CHANNEL_SALES_SQL = """
SELECT
    o.channel,
    COUNT(*) AS paid_order_count,
    SUM(o.amount) AS sales_amount
FROM orders AS o
WHERE o.status = 'paid'
    AND o.created_at >= CURRENT_TIMESTAMP
        - (%(days)s * INTERVAL '1 day')
GROUP BY o.channel
ORDER BY sales_amount DESC;
"""


PRODUCT_SALES_SQL = """
SELECT
    p.product_id,
    p.name AS product_name,
    SUM(oi.quantity) AS units_sold,
    SUM(oi.quantity * oi.unit_price) AS sales_amount
FROM order_items AS oi
JOIN orders AS o
    ON o.order_id = oi.order_id
JOIN products AS p
    ON p.product_id = oi.product_id
WHERE o.status = 'paid'
    AND o.created_at >= CURRENT_TIMESTAMP
        - (%(days)s * INTERVAL '1 day')
GROUP BY p.product_id, p.name
ORDER BY sales_amount DESC
LIMIT %(limit)s;
"""

REFUND_STATUS_SQL = """
SELECT
    r.status,
    COUNT(*) AS refund_count,
    SUM(r.refund_amount) AS refund_amount
FROM refunds AS r
WHERE r.created_at >= CURRENT_TIMESTAMP
    - (%(days)s * INTERVAL '1 day')
GROUP BY r.status
ORDER BY refund_amount DESC;
"""


ORDER_STATUS_SQL = """
SELECT
    o.status,
    COUNT(*) AS order_count,
    SUM(o.amount) AS order_amount
FROM orders AS o
WHERE o.created_at >= CURRENT_TIMESTAMP
    - (%(days)s * INTERVAL '1 day')
GROUP BY o.status
ORDER BY order_count DESC, order_amount DESC;
"""


def get_channel_sales_summary(
    connection: DatabaseConnection,
    days: int = 30,
) -> list[ChannelSalesSummary]:
    if not 1 <= days <= 365:
        raise ValueError("days must be between 1 and 365")

    rows = connection.execute(
        CHANNEL_SALES_SQL,
        {"days": days},
    ).fetchall()

    return [ChannelSalesSummary.model_validate(row) for row in rows]


def get_product_sales_summary(
    connection: DatabaseConnection,
    days: int = 30,
    limit: int = 10,
) -> list[ProductSalesSummary]:
    if not 1 <= days <= 365:
        raise ValueError("days must be between 1 and 365")

    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")

    rows = connection.execute(
        PRODUCT_SALES_SQL,
        {
            "days": days,
            "limit": limit,
        },
    ).fetchall()

    return [ProductSalesSummary.model_validate(row) for row in rows]


def get_refund_status_summary(
    connection: DatabaseConnection,
    days: int = 30,
) -> list[RefundStatusSummary]:
    if not 1 <= days <= 365:
        raise ValueError("days must be between 1 and 365")

    rows = connection.execute(
        REFUND_STATUS_SQL,
        {"days": days},
    ).fetchall()

    return [
        RefundStatusSummary.model_validate(row)
        for row in rows
    ]


def get_order_status_summary(
    connection: DatabaseConnection,
    days: int = 30,
) -> list[OrderStatusSummary]:
    if not 1 <= days <= 365:
        raise ValueError("days must be between 1 and 365")

    rows = connection.execute(
        ORDER_STATUS_SQL,
        {"days": days},
    ).fetchall()

    return [OrderStatusSummary.model_validate(row) for row in rows]
