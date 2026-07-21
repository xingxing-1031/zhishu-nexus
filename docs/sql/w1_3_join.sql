SELECT
    oi.order_id,
    p.name AS product_name,
    oi.quantity,
    oi.unit_price,
    oi.quantity * oi.unit_price AS line_amount
FROM order_items AS oi
JOIN products AS p
    ON p.product_id = oi.product_id
WHERE oi.order_id = 'ORD-001';


SELECT
    oi.order_id,
    SUM(oi.quantity * oi.unit_price) AS order_amount
FROM order_items AS oi
WHERE oi.order_id = 'ORD-001'
GROUP BY oi.order_id;


SELECT
    oi.order_id,
    SUM(oi.quantity * oi.unit_price) AS order_amount
FROM order_items AS oi
GROUP BY oi.order_id
ORDER BY order_amount DESC;


SELECT
    o.order_id,
    o.channel,
    SUM(oi.quantity * oi.unit_price) AS order_amount
FROM orders AS o
JOIN order_items AS oi
    ON o.order_id=oi.order_id
GROUP BY o.order_id, o.channel
ORDER BY order_amount DESC
LIMIT 5;


SELECT
    o.channel,
    COUNT(*) AS paid_order_count,
    SUM(o.amount) AS sales_amount
FROM orders AS o
WHERE o.status='paid'
GROUP BY o.channel
HAVING SUM(o.amount) >= 10000
ORDER BY sales_amount DESC;


SELECT
    o.channel,
    COUNT(*) AS joined_row_count,
    COUNT(DISTINCT o.order_id) AS paid_order_count
FROM orders AS o
JOIN order_items AS oi
    ON o.order_id = oi.order_id
WHERE o.status = 'paid'
GROUP BY o.channel;


SELECT
    o.order_id,
    o.channel,
    o.amount AS order_amount,
    SUM(r.refund_amount) AS refunded_amount
FROM orders AS o
JOIN refunds AS r
    ON r.order_id = o.order_id
WHERE r.status = 'completed'
GROUP BY o.order_id, o.channel, o.amount;


SELECT
    o.order_id,
    o.channel,
    o.amount,
    o.status
FROM orders AS o
WHERE o.status = 'paid'
    AND (o.channel = '淘宝' OR o.channel = '京东')
    AND o.amount BETWEEN 100 AND 1000
ORDER BY o.amount DESC;


SELECT
    o.order_id,
    o.channel,
    o.amount
FROM orders AS o
LEFT JOIN refunds AS r
    ON r.order_id = o.order_id
WHERE r.refund_id IS NULL;


SELECT
    o.order_id,
    o.amount,
    CASE
        WHEN o.amount >= 1000 THEN '高金额'
        WHEN o.amount >= 100 THEN '中金额'
        ELSE '低金额'
    END AS amount_level
FROM orders AS o;


SELECT
    o.order_id,
    o.amount AS order_amount,
    COALESCE(SUM(r.refund_amount), 0) AS refunded_amount
FROM orders AS o
LEFT JOIN refunds AS r
    ON r.order_id = o.order_id
    AND r.status = 'completed'
GROUP BY o.order_id, o.amount;