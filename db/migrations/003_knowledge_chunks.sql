BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE knowledge_chunks (
    source_id TEXT PRIMARY KEY,
    corpus_id TEXT NOT NULL,
    knowledge_type TEXT NOT NULL,
    version TEXT,
    related_tables TEXT[] NOT NULL,
    content TEXT NOT NULL,
    content_sha256 CHAR(64) NOT NULL,
    embedding_model TEXT NOT NULL,
    embedding VECTOR(1024) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT knowledge_chunks_source_id_not_blank
        CHECK (length(btrim(source_id)) > 0),
    CONSTRAINT knowledge_chunks_corpus_id_not_blank
        CHECK (length(btrim(corpus_id)) > 0),
    CONSTRAINT knowledge_chunks_type_valid
        CHECK (knowledge_type IN ('metric', 'table', 'join')),
    CONSTRAINT knowledge_chunks_version_consistent
        CHECK (
            (knowledge_type = 'metric' AND version IS NOT NULL)
            OR (knowledge_type <> 'metric' AND version IS NULL)
        ),
    CONSTRAINT knowledge_chunks_related_tables_not_empty
        CHECK (cardinality(related_tables) > 0),
    CONSTRAINT knowledge_chunks_content_not_blank
        CHECK (length(btrim(content)) > 0),
    CONSTRAINT knowledge_chunks_hash_valid
        CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT knowledge_chunks_embedding_model_not_blank
        CHECK (length(btrim(embedding_model)) > 0),
    CONSTRAINT knowledge_chunks_embedding_dimension
        CHECK (vector_dims(embedding) = 1024)
);

CREATE INDEX idx_knowledge_chunks_type
    ON knowledge_chunks(knowledge_type);

CREATE INDEX idx_knowledge_chunks_model
    ON knowledge_chunks(embedding_model);

COMMIT;
