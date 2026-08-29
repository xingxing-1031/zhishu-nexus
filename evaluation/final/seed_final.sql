-- Controlled synthetic retail snapshot for the final evaluation release.
-- It is deterministic: do not replace the reference time with CURRENT_TIMESTAMP.
BEGIN;

INSERT INTO products (product_id, name, category, unit_price)
VALUES
    ('PROD-001', '智能手机', '数码', 7299.00),
    ('PROD-002', '无线耳机', '数码', 899.00),
    ('PROD-003', '水果礼盒', '食品', 129.00),
    ('PROD-004', '数据线赠品', '配件', 0.00),
    ('PROD-005', '人体工学椅', '家居', 1699.00),
    ('PROD-006', '机械键盘', '数码', 599.00),
    ('PROD-007', '智能手表', '数码', 1299.00),
    ('PROD-008', '便携充电宝', '配件', 159.00),
    ('PROD-009', '咖啡豆礼盒', '食品', 168.00),
    ('PROD-010', '护肤套装', '个护', 399.00),
    ('PROD-011', '升降办公桌', '家居', 2199.00),
    ('PROD-012', '显示器支架', '办公', 329.00),
    ('PROD-013', '蓝牙音箱', '数码', 499.00),
    ('PROD-014', '保温杯', '家居', 129.00),
    ('PROD-015', '坚果组合装', '食品', 99.00),
    ('PROD-016', '洗护旅行装', '个护', 79.00)
ON CONFLICT (product_id) DO UPDATE SET
    name = EXCLUDED.name,
    category = EXCLUDED.category,
    unit_price = EXCLUDED.unit_price;

WITH generated_orders AS (
    SELECT
        series,
        'FINAL-ORD-' || lpad(series::text, 4, '0') AS order_id,
        CASE series % 4
            WHEN 0 THEN '京东'
            WHEN 1 THEN '淘宝'
            WHEN 2 THEN '抖音'
            ELSE '微信小程序'
        END AS channel,
        CASE
            WHEN series % 13 = 0 THEN 'cancelled'
            WHEN series % 11 = 0 THEN 'pending'
            WHEN series % 7 = 0 THEN 'completed'
            WHEN series % 5 = 0 THEN 'shipped'
            ELSE 'paid'
        END AS status,
        TIMESTAMPTZ '2026-08-28 12:00:00+08'
            - make_interval(days => series % 180)
            - make_interval(hours => (series * 3) % 24) AS created_at
    FROM generate_series(1, 1000) AS series
), generated_items AS (
    SELECT
        orders.series,
        orders.order_id,
        item_no,
        1 + ((orders.series + item_no) % 3) AS quantity,
        1 + ((orders.series * 5 + item_no * 3) % 16) AS product_number
    FROM generated_orders AS orders
    CROSS JOIN LATERAL generate_series(1, 1 + (orders.series % 3)) AS item_no
), order_totals AS (
    SELECT
        items.order_id,
        SUM(
            items.quantity * CASE items.product_number
                WHEN 1 THEN 7299.00 WHEN 2 THEN 899.00
                WHEN 3 THEN 129.00 WHEN 4 THEN 0.00
                WHEN 5 THEN 1699.00 WHEN 6 THEN 599.00
                WHEN 7 THEN 1299.00 WHEN 8 THEN 159.00
                WHEN 9 THEN 168.00 WHEN 10 THEN 399.00
                WHEN 11 THEN 2199.00 WHEN 12 THEN 329.00
                WHEN 13 THEN 499.00 WHEN 14 THEN 129.00
                WHEN 15 THEN 99.00 ELSE 79.00
            END
        )::NUMERIC(12, 2) AS amount
    FROM generated_items AS items
    GROUP BY items.order_id
)
INSERT INTO orders (order_id, channel, amount, status, created_at)
SELECT orders.order_id, orders.channel, totals.amount, orders.status, orders.created_at
FROM generated_orders AS orders
JOIN order_totals AS totals USING (order_id)
ON CONFLICT (order_id) DO UPDATE SET
    channel = EXCLUDED.channel,
    amount = EXCLUDED.amount,
    status = EXCLUDED.status,
    created_at = EXCLUDED.created_at;

WITH generated_items AS (
    SELECT
        series,
        'FINAL-ORD-' || lpad(series::text, 4, '0') AS order_id,
        item_no,
        1 + ((series + item_no) % 3) AS quantity,
        1 + ((series * 5 + item_no * 3) % 16) AS product_number
    FROM generate_series(1, 1000) AS series
    CROSS JOIN LATERAL generate_series(1, 1 + (series % 3)) AS item_no
)
INSERT INTO order_items (order_item_id, order_id, product_id, quantity, unit_price)
SELECT
    'FINAL-ITEM-' || lpad(series::text, 4, '0') || '-' || item_no,
    order_id,
    'PROD-' || lpad(product_number::text, 3, '0'),
    quantity,
    CASE product_number
        WHEN 1 THEN 7299.00 WHEN 2 THEN 899.00
        WHEN 3 THEN 129.00 WHEN 4 THEN 0.00
        WHEN 5 THEN 1699.00 WHEN 6 THEN 599.00
        WHEN 7 THEN 1299.00 WHEN 8 THEN 159.00
        WHEN 9 THEN 168.00 WHEN 10 THEN 399.00
        WHEN 11 THEN 2199.00 WHEN 12 THEN 329.00
        WHEN 13 THEN 499.00 WHEN 14 THEN 129.00
        WHEN 15 THEN 99.00 ELSE 79.00
    END
FROM generated_items
ON CONFLICT (order_item_id) DO UPDATE SET
    order_id = EXCLUDED.order_id,
    product_id = EXCLUDED.product_id,
    quantity = EXCLUDED.quantity,
    unit_price = EXCLUDED.unit_price;

INSERT INTO refunds (refund_id, order_id, refund_amount, reason, status, created_at)
SELECT
    'FINAL-REF-' || lpad(series::text, 4, '0'),
    'FINAL-ORD-' || lpad((series * 13)::text, 4, '0'),
    (40 + series * 11)::NUMERIC(12, 2),
    CASE series % 5
        WHEN 0 THEN '商品与描述不符'
        WHEN 1 THEN '物流破损'
        WHEN 2 THEN '尺寸或规格不合适'
        WHEN 3 THEN '重复下单'
        ELSE '质量问题'
    END,
    CASE series % 4
        WHEN 0 THEN 'requested'
        WHEN 1 THEN 'approved'
        WHEN 2 THEN 'completed'
        ELSE 'rejected'
    END,
    TIMESTAMPTZ '2026-08-28 12:00:00+08'
        - make_interval(days => (series * 5) % 90)
FROM generate_series(1, 76) AS series
ON CONFLICT (refund_id) DO UPDATE SET
    order_id = EXCLUDED.order_id,
    refund_amount = EXCLUDED.refund_amount,
    reason = EXCLUDED.reason,
    status = EXCLUDED.status,
    created_at = EXCLUDED.created_at;

COMMIT;
