BEGIN;

-- Product prices are current catalog prices. Order item prices below are
-- transaction snapshots and may intentionally differ from these values.
INSERT INTO products (product_id, name, category, unit_price)
VALUES
    ('PROD-001', '智能手机', '数码', 7299.00),
    ('PROD-002', '无线耳机', '数码', 899.00),
    ('PROD-003', '水果礼盒', '食品', 129.00),
    ('PROD-004', '数据线赠品', '配件', 0.00),
    ('PROD-005', '人体工学椅', '家居', 1699.00),
    ('PROD-006', '机械键盘', '数码', 599.00)
ON CONFLICT (product_id) DO UPDATE SET
    name = EXCLUDED.name,
    category = EXCLUDED.category,
    unit_price = EXCLUDED.unit_price;

INSERT INTO orders (order_id, channel, amount, status, created_at)
VALUES
    ('ORD-001', '淘宝', 9000.00, 'paid',      CURRENT_TIMESTAMP - INTERVAL '2 days'),
    ('ORD-002', '京东', 800.00,  'paid',      CURRENT_TIMESTAMP - INTERVAL '5 days'),
    ('ORD-003', '抖音', 12000.00,'paid',      CURRENT_TIMESTAMP - INTERVAL '45 days'),
    ('ORD-004', '淘宝', 300.00,  'pending',   CURRENT_TIMESTAMP - INTERVAL '1 day'),
    ('ORD-005', '京东', 1500.00, 'completed', CURRENT_TIMESTAMP - INTERVAL '12 days'),
    ('ORD-006', '抖音', 200.00,  'cancelled', CURRENT_TIMESTAMP - INTERVAL '8 days'),
    ('ORD-007', '淘宝', 0.00,    'shipped',   CURRENT_TIMESTAMP - INTERVAL '3 days'),
    ('ORD-008', '京东', 10500.00,'paid',      CURRENT_TIMESTAMP - INTERVAL '18 days'),
    ('ORD-009', '淘宝', 600.00,  'paid',      CURRENT_TIMESTAMP - INTERVAL '25 days'),
    ('ORD-010', '抖音', 280.00,  'completed', CURRENT_TIMESTAMP - INTERVAL '60 days')
ON CONFLICT (order_id) DO UPDATE SET
    channel = EXCLUDED.channel,
    amount = EXCLUDED.amount,
    status = EXCLUDED.status,
    created_at = EXCLUDED.created_at;

INSERT INTO order_items (
    order_item_id,
    order_id,
    product_id,
    quantity,
    unit_price
)
VALUES
    ('ITEM-001', 'ORD-001', 'PROD-001', 1, 7000.00),
    ('ITEM-002', 'ORD-001', 'PROD-002', 2, 1000.00),
    ('ITEM-003', 'ORD-002', 'PROD-006', 1, 600.00),
    ('ITEM-004', 'ORD-002', 'PROD-003', 2, 100.00),
    ('ITEM-005', 'ORD-003', 'PROD-001', 2, 6000.00),
    ('ITEM-006', 'ORD-004', 'PROD-003', 3, 100.00),
    ('ITEM-007', 'ORD-005', 'PROD-005', 1, 1500.00),
    ('ITEM-008', 'ORD-006', 'PROD-003', 2, 100.00),
    ('ITEM-009', 'ORD-007', 'PROD-004', 1, 0.00),
    ('ITEM-010', 'ORD-008', 'PROD-001', 1, 7000.00),
    ('ITEM-011', 'ORD-008', 'PROD-005', 2, 1750.00),
    ('ITEM-012', 'ORD-009', 'PROD-006', 1, 600.00),
    ('ITEM-013', 'ORD-010', 'PROD-003', 2, 140.00)
ON CONFLICT (order_item_id) DO UPDATE SET
    order_id = EXCLUDED.order_id,
    product_id = EXCLUDED.product_id,
    quantity = EXCLUDED.quantity,
    unit_price = EXCLUDED.unit_price;

INSERT INTO refunds (
    refund_id,
    order_id,
    refund_amount,
    reason,
    status,
    created_at
)
VALUES
    ('REF-001', 'ORD-001', 1000.00, '耳机质量问题', 'completed', CURRENT_TIMESTAMP - INTERVAL '1 day'),
    ('REF-002', 'ORD-005', 200.00,  '商品破损',     'requested', CURRENT_TIMESTAMP - INTERVAL '10 days'),
    ('REF-003', 'ORD-008', 500.00,  '价保补差',     'approved',  CURRENT_TIMESTAMP - INTERVAL '15 days'),
    ('REF-004', 'ORD-003', 1200.00, '部分退货',     'completed', CURRENT_TIMESTAMP - INTERVAL '40 days'),
    ('REF-005', 'ORD-009', 100.00,  '不符合退款条件','rejected',  CURRENT_TIMESTAMP - INTERVAL '20 days'),
    ('REF-006', 'ORD-001', 500.00,  '补偿退款',     'completed', CURRENT_TIMESTAMP - INTERVAL '12 hours')
ON CONFLICT (refund_id) DO UPDATE SET
    order_id = EXCLUDED.order_id,
    refund_amount = EXCLUDED.refund_amount,
    reason = EXCLUDED.reason,
    status = EXCLUDED.status,
    created_at = EXCLUDED.created_at;

COMMIT;
