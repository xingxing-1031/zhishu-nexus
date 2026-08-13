BEGIN;

CREATE TABLE agent_conversations (
    conversation_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    confirmed_constraints TEXT[] NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (conversation_id, user_id)
);

CREATE TABLE agent_conversation_turns (
    conversation_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    evidence_ids TEXT[] NOT NULL DEFAULT '{}',
    confirmed_constraints TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (conversation_id, request_id),
    FOREIGN KEY (conversation_id, user_id)
        REFERENCES agent_conversations(conversation_id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT agent_turn_role_valid
        CHECK (role IN ('user', 'assistant', 'system')),
    CONSTRAINT agent_turn_content_not_blank
        CHECK (length(btrim(content)) > 0)
);

CREATE INDEX idx_agent_turns_conversation_time
    ON agent_conversation_turns(conversation_id, user_id, created_at DESC);

COMMIT;
