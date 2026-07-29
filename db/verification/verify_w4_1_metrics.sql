DO $$
DECLARE
    actual_sales_amount NUMERIC(12, 2);
    actual_order_count INTEGER;
    actual_units_sold INTEGER;
    actual_refund_amount NUMERIC(12, 2);
    actual_refund_count INTEGER;
    actual_average_order_value NUMERIC(12, 2);
BEGIN
    SELECT
        COALESCE(SUM(oi.quantity * oi.unit_price), 0)
    INTO actual_sales_amount
    FROM orders AS o
    JOIN order_items AS oi ON oi.order_id = o.order_id
    WHERE o.status = 'paid';

    IF actual_sales_amount <> 32900.00 THEN
        RAISE EXCEPTION
            'sales_amount.v1 expected 32900.00, found %',
            actual_sales_amount;
    END IF;

    SELECT
        COUNT(DISTINCT o.order_id),
        COALESCE(SUM(oi.quantity), 0)
    INTO actual_order_count, actual_units_sold
    FROM orders AS o
    JOIN order_items AS oi ON oi.order_id = o.order_id
    WHERE o.status = 'paid';

    IF actual_order_count <> 5 THEN
        RAISE EXCEPTION
            'order_count.v1 expected 5, found %',
            actual_order_count;
    END IF;

    IF actual_units_sold <> 12 THEN
        RAISE EXCEPTION
            'units_sold.v1 expected 12, found %',
            actual_units_sold;
    END IF;

    SELECT
        COALESCE(SUM(r.refund_amount), 0),
        COUNT(DISTINCT r.refund_id)
    INTO actual_refund_amount, actual_refund_count
    FROM refunds AS r;

    IF actual_refund_amount <> 3500.00 THEN
        RAISE EXCEPTION
            'refund_amount.v1 expected 3500.00, found %',
            actual_refund_amount;
    END IF;

    IF actual_refund_count <> 6 THEN
        RAISE EXCEPTION
            'refund_count.v1 expected 6, found %',
            actual_refund_count;
    END IF;

    SELECT
        SUM(o.amount) / NULLIF(COUNT(DISTINCT o.order_id), 0)
    INTO actual_average_order_value
    FROM orders AS o
    WHERE o.status = 'paid';

    IF actual_average_order_value <> 6580.00 THEN
        RAISE EXCEPTION
            'average_order_value.v1 expected 6580.00, found %',
            actual_average_order_value;
    END IF;
END
$$;

SELECT 'W4-1 metric verification passed' AS result;
