BEGIN;

CREATE TABLE analysis_trace_events (
    trace_event_id BIGSERIAL PRIMARY KEY,
    request_id TEXT NOT NULL,
    component TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    duration_ms INTEGER,
    error_type TEXT,
    error_message TEXT,
    retry_delay_ms INTEGER,

    CONSTRAINT analysis_trace_status_valid
        CHECK (
            status IN (
                'started',
                'succeeded',
                'failed',
                'retry_scheduled',
                'rejected',
                'pending',
                'degraded'
            )
        ),
    CONSTRAINT analysis_trace_attempt_positive CHECK (attempt >= 1),
    CONSTRAINT analysis_trace_duration_non_negative
        CHECK (duration_ms IS NULL OR duration_ms >= 0),
    CONSTRAINT analysis_trace_retry_delay_non_negative
        CHECK (retry_delay_ms IS NULL OR retry_delay_ms >= 0)
);

CREATE INDEX idx_analysis_trace_request
    ON analysis_trace_events(request_id, trace_event_id);

CREATE INDEX idx_analysis_trace_component_status
    ON analysis_trace_events(component, status);

COMMIT;
