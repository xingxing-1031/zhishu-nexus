BEGIN;

ALTER TABLE query_audit_logs
    ADD COLUMN event_key TEXT;

UPDATE query_audit_logs
SET event_key = 'legacy:query:' || audit_id;

ALTER TABLE query_audit_logs
    ALTER COLUMN event_key SET NOT NULL;

CREATE UNIQUE INDEX uq_query_audit_event_key
    ON query_audit_logs(event_key);

ALTER TABLE query_approval_logs
    ADD COLUMN event_key TEXT;

UPDATE query_approval_logs
SET event_key = 'legacy:approval:' || approval_audit_id;

ALTER TABLE query_approval_logs
    ALTER COLUMN event_key SET NOT NULL;

CREATE UNIQUE INDEX uq_query_approval_event_key
    ON query_approval_logs(event_key);

CREATE TABLE analysis_request_registry (
    request_id TEXT PRIMARY KEY,
    request_fingerprint CHAR(64) NOT NULL,
    user_id TEXT NOT NULL,
    access_role TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT analysis_request_role_valid
        CHECK (access_role IN ('analyst', 'admin')),
    CONSTRAINT analysis_request_status_valid
        CHECK (
            status IN (
                'running',
                'pending',
                'completed',
                'degraded',
                'rejected',
                'failed'
            )
        ),
    CONSTRAINT analysis_request_fingerprint_valid
        CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT analysis_request_error_consistent
        CHECK (
            (status = 'failed' AND error IS NOT NULL)
            OR (status <> 'failed' AND error IS NULL)
        )
);

CREATE INDEX idx_analysis_request_user_id
    ON analysis_request_registry(user_id);

CREATE INDEX idx_analysis_request_status
    ON analysis_request_registry(status);

COMMIT;
