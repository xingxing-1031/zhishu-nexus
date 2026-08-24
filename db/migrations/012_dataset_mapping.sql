BEGIN;

ALTER TABLE dataset_registry
    ADD COLUMN mapping JSONB,
    ADD COLUMN mapping_confirmed BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE dataset_registry
    ADD CONSTRAINT dataset_mapping_object
        CHECK (mapping IS NULL OR jsonb_typeof(mapping) = 'object');

COMMIT;
