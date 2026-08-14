BEGIN;

CREATE TABLE workspace_conversations (
    user_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    title TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (user_id, conversation_id),
    CONSTRAINT workspace_conversation_payload_object
        CHECK (jsonb_typeof(payload) = 'object')
);

CREATE INDEX idx_workspace_conversations_user_updated
    ON workspace_conversations(user_id, updated_at DESC);

COMMIT;
