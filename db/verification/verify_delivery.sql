DO $$
DECLARE
    missing_relations TEXT[];
    demo_order_count INTEGER;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_extension
        WHERE extname = 'vector'
    ) THEN
        RAISE EXCEPTION 'pgvector extension is not enabled';
    END IF;

    SELECT array_agg(required_relation)
    INTO missing_relations
    FROM unnest(ARRAY[
        'orders',
        'products',
        'order_items',
        'refunds',
        'query_audit_logs',
        'knowledge_chunks',
        'query_approval_logs',
        'analysis_request_registry',
        'analysis_trace_events'
    ]) AS required_relation
    WHERE to_regclass('public.' || required_relation) IS NULL;

    IF missing_relations IS NOT NULL THEN
        RAISE EXCEPTION 'missing delivery relations: %', missing_relations;
    END IF;

    SELECT COUNT(*)
    INTO demo_order_count
    FROM orders
    WHERE order_id LIKE 'ORD-%';

    IF demo_order_count <> 10 THEN
        RAISE EXCEPTION
            'expected 10 demo orders after initialization, found %',
            demo_order_count;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'query_audit_logs'
          AND column_name = 'event_key'
          AND is_nullable = 'NO'
    ) OR NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'query_approval_logs'
          AND column_name = 'event_key'
          AND is_nullable = 'NO'
    ) THEN
        RAISE EXCEPTION 'idempotent audit event keys are missing';
    END IF;
END
$$;

SELECT 'W6-3 delivery database verification passed' AS result;
