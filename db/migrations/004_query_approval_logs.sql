BEGIN;

CREATE TABLE query_approval_logs (
    approval_audit_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id TEXT NOT NULL,
    requester_id TEXT NOT NULL,
    access_role TEXT NOT NULL,
    sql TEXT NOT NULL,
    status TEXT NOT NULL,
    reasons TEXT[] NOT NULL,
    reviewer_id TEXT,
    decision_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT query_approval_role_valid
        CHECK (access_role IN ('analyst', 'admin')),
    CONSTRAINT query_approval_status_valid
        CHECK (status IN ('pending', 'approved', 'rejected')),
    CONSTRAINT query_approval_reasons_not_empty
        CHECK (cardinality(reasons) > 0),
    CONSTRAINT query_approval_resolution_consistent
        CHECK (
            (status = 'pending' AND reviewer_id IS NULL)
            OR (status IN ('approved', 'rejected') AND reviewer_id IS NOT NULL)
        )
);

CREATE INDEX idx_query_approval_request_id
    ON query_approval_logs(request_id);

CREATE INDEX idx_query_approval_created_at
    ON query_approval_logs(created_at);

COMMIT;
