BEGIN;

CREATE TABLE query_audit_logs (
    audit_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    original_sql TEXT NOT NULL,
    executed_sql TEXT,
    status TEXT NOT NULL,
    reason TEXT,
    row_count INTEGER,
    duration_ms NUMERIC(12, 3) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT query_audit_status_valid
        CHECK (status IN ('succeeded', 'rejected', 'failed')),
    CONSTRAINT query_audit_row_count_non_negative
        CHECK (row_count IS NULL OR row_count >= 0),
    CONSTRAINT query_audit_duration_non_negative
        CHECK (duration_ms >= 0)
);

CREATE INDEX idx_query_audit_request_id
    ON query_audit_logs(request_id);

CREATE INDEX idx_query_audit_created_at
    ON query_audit_logs(created_at);

COMMIT;
