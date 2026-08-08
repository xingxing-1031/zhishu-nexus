BEGIN;

ALTER TABLE analysis_request_registry
    ADD COLUMN original_question TEXT,
    ADD COLUMN max_rows INTEGER;

ALTER TABLE analysis_request_registry
    ADD CONSTRAINT analysis_request_original_question_not_blank
        CHECK (
            original_question IS NULL
            OR length(btrim(original_question)) > 0
        ),
    ADD CONSTRAINT analysis_request_max_rows_valid
        CHECK (max_rows IS NULL OR max_rows BETWEEN 1 AND 1000);

COMMIT;
