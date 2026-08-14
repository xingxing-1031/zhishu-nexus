BEGIN;

CREATE TABLE agent_request_runs (
    request_id TEXT PRIMARY KEY,
    request_fingerprint CHAR(64) NOT NULL,
    conversation_id TEXT,
    user_id TEXT NOT NULL,
    access_role TEXT NOT NULL,
    agent_mode TEXT NOT NULL,
    original_question TEXT NOT NULL,
    auditable BOOLEAN NOT NULL DEFAULT FALSE,
    status TEXT NOT NULL,
    tool_names TEXT[] NOT NULL DEFAULT '{}',
    evidence_count INTEGER NOT NULL DEFAULT 0,
    approval_required BOOLEAN NOT NULL DEFAULT FALSE,
    failure_reason TEXT,
    response_payload JSONB,
    duration_ms NUMERIC(12, 3),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT agent_run_role_valid
        CHECK (access_role IN ('analyst', 'admin')),
    CONSTRAINT agent_run_mode_valid
        CHECK (agent_mode IN ('general', 'knowledge', 'data', 'collaboration')),
    CONSTRAINT agent_run_status_valid
        CHECK (status IN ('running', 'pending', 'succeeded', 'degraded', 'refused', 'failed')),
    CONSTRAINT agent_run_fingerprint_valid
        CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT agent_run_question_not_blank
        CHECK (length(btrim(original_question)) > 0),
    CONSTRAINT agent_run_evidence_count_non_negative
        CHECK (evidence_count >= 0),
    CONSTRAINT agent_run_duration_non_negative
        CHECK (duration_ms IS NULL OR duration_ms >= 0),
    CONSTRAINT agent_run_response_object
        CHECK (response_payload IS NULL OR jsonb_typeof(response_payload) = 'object')
);

CREATE INDEX idx_agent_runs_user_created
    ON agent_request_runs(user_id, created_at DESC);

CREATE INDEX idx_agent_runs_auditable_created
    ON agent_request_runs(auditable, created_at DESC);

CREATE INDEX idx_agent_runs_conversation
    ON agent_request_runs(conversation_id, created_at DESC);

INSERT INTO agent_request_runs (
    request_id,
    request_fingerprint,
    conversation_id,
    user_id,
    access_role,
    agent_mode,
    original_question,
    auditable,
    status,
    tool_names,
    approval_required,
    failure_reason,
    created_at,
    updated_at
)
SELECT
    registry.request_id,
    registry.request_fingerprint,
    NULL,
    registry.user_id,
    registry.access_role,
    'data',
    COALESCE(registry.original_question, '历史经营数据请求'),
    TRUE,
    CASE registry.status
        WHEN 'completed' THEN 'succeeded'
        WHEN 'rejected' THEN 'refused'
        ELSE registry.status
    END,
    ARRAY['sql.query']::TEXT[],
    EXISTS (
        SELECT 1
        FROM query_approval_logs AS approval
        WHERE approval.request_id = registry.request_id
    ),
    registry.error,
    registry.created_at,
    registry.updated_at
FROM analysis_request_registry AS registry
ON CONFLICT (request_id) DO NOTHING;

COMMIT;
