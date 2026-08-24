BEGIN;

CREATE TABLE dataset_registry (
    dataset_id TEXT NOT NULL,
    dataset_name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_ref TEXT,
    schema_name TEXT NOT NULL,
    version INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'uploaded',
    row_count BIGINT NOT NULL DEFAULT 0,
    quality_report JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (dataset_id, version),
    CONSTRAINT dataset_source_type_valid
        CHECK (source_type IN ('postgres', 'csv', 'parquet')),
    CONSTRAINT dataset_status_valid
        CHECK (status IN (
            'uploaded',
            'profiling',
            'needs_mapping',
            'ready',
            'failed',
            'archived'
        )),
    CONSTRAINT dataset_version_positive CHECK (version >= 1),
    CONSTRAINT dataset_row_count_non_negative CHECK (row_count >= 0),
    CONSTRAINT dataset_schema_name_safe
        CHECK (schema_name ~ '^staging_[a-z0-9_]+$'),
    CONSTRAINT dataset_quality_report_object
        CHECK (quality_report IS NULL OR jsonb_typeof(quality_report) = 'object')
);

CREATE INDEX idx_dataset_registry_status
    ON dataset_registry(status);

CREATE INDEX idx_dataset_registry_dataset
    ON dataset_registry(dataset_id, version DESC);

CREATE TABLE dataset_quality_reports (
    report_id BIGSERIAL PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    report JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT dataset_quality_report_dataset_fk
        FOREIGN KEY (dataset_id, version)
        REFERENCES dataset_registry(dataset_id, version)
        ON DELETE CASCADE,
    CONSTRAINT dataset_quality_report_object
        CHECK (jsonb_typeof(report) = 'object')
);

CREATE INDEX idx_dataset_quality_reports_dataset
    ON dataset_quality_reports(dataset_id, version, created_at DESC);

COMMIT;
