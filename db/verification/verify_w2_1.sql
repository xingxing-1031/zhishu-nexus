DO $$
DECLARE
    actual_count INTEGER;
    invalid_status_rejected BOOLEAN := FALSE;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_extension
        WHERE extname = 'vector'
    ) THEN
        RAISE EXCEPTION 'pgvector extension is not enabled';
    END IF;

    IF to_regclass('public.orders') IS NULL
        OR to_regclass('public.products') IS NULL
        OR to_regclass('public.order_items') IS NULL
        OR to_regclass('public.refunds') IS NULL THEN
        RAISE EXCEPTION 'one or more business tables are missing';
    END IF;

    SELECT COUNT(*) INTO actual_count
    FROM orders
    WHERE order_id = ANY (ARRAY[
        'ORD-001', 'ORD-002', 'ORD-003', 'ORD-004', 'ORD-005',
        'ORD-006', 'ORD-007', 'ORD-008', 'ORD-009', 'ORD-010'
    ]);
    IF actual_count <> 10 THEN
        RAISE EXCEPTION 'expected 10 demo orders, found %', actual_count;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM orders AS o
        JOIN order_items AS oi ON oi.order_id = o.order_id
        GROUP BY o.order_id, o.amount
        HAVING o.amount <> SUM(oi.quantity * oi.unit_price)
    ) THEN
        RAISE EXCEPTION 'an order amount does not match its item total';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM orders
        WHERE amount = 0
    ) THEN
        RAISE EXCEPTION 'zero-amount order scenario is missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM orders
        WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
    ) OR NOT EXISTS (
        SELECT 1
        FROM orders
        WHERE created_at < CURRENT_TIMESTAMP - INTERVAL '30 days'
    ) THEN
        RAISE EXCEPTION 'recent and historical order scenarios are required';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM order_items
        GROUP BY order_id
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'multi-item order scenario is missing';
    END IF;

    BEGIN
        INSERT INTO orders (order_id, channel, amount, status, created_at)
        VALUES ('VERIFY-INVALID-STATUS', 'test', 1, 'unknown', CURRENT_TIMESTAMP);
    EXCEPTION
        WHEN check_violation THEN
            invalid_status_rejected := TRUE;
    END;

    IF NOT invalid_status_rejected THEN
        DELETE FROM orders WHERE order_id = 'VERIFY-INVALID-STATUS';
        RAISE EXCEPTION 'orders status constraint did not reject invalid input';
    END IF;
END
$$;

SELECT 'W2-1 database verification passed' AS result;
