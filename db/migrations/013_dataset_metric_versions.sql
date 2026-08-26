BEGIN;

CREATE TABLE dataset_metric_versions (
    dataset_id TEXT NOT NULL,
    dataset_version INTEGER NOT NULL,
    metric_id TEXT NOT NULL,
    metric_version TEXT NOT NULL,
    name TEXT NOT NULL,
    definition TEXT NOT NULL,
    aggregation TEXT NOT NULL,
    formula TEXT NOT NULL,
    source_role TEXT NOT NULL,
    source_table TEXT NOT NULL,
    source_column TEXT NOT NULL,
    supported_dimensions JSONB NOT NULL DEFAULT '[]'::jsonb,
    fixed_filters JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'proposed',
    effective_from TIMESTAMPTZ,
    confirmed_by TEXT,
    confirmed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT dataset_metric_versions_pkey
        PRIMARY KEY (dataset_id, dataset_version, metric_id, metric_version),
    CONSTRAINT dataset_metric_version_valid
        CHECK (metric_version ~ '^v[1-9][0-9]*$'),
    CONSTRAINT dataset_metric_aggregation_valid
        CHECK (aggregation IN ('SUM', 'COUNT_DISTINCT', 'RATIO')),
    CONSTRAINT dataset_metric_status_valid
        CHECK (status IN ('proposed', 'confirmed', 'archived')),
    CONSTRAINT dataset_metric_dimensions_array
        CHECK (jsonb_typeof(supported_dimensions) = 'array'),
    CONSTRAINT dataset_metric_filters_array
        CHECK (jsonb_typeof(fixed_filters) = 'array')
);

CREATE INDEX dataset_metric_versions_lookup_idx
    ON dataset_metric_versions (dataset_id, dataset_version, metric_id);

COMMIT;
