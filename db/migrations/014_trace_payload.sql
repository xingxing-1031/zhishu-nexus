BEGIN;

ALTER TABLE analysis_trace_events
    ADD COLUMN payload JSONB;

COMMIT;
