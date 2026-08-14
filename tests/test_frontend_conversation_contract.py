from pathlib import Path

FRONTEND = Path(__file__).parents[1] / "frontend" / "src"


def test_history_adapter_keeps_summary_as_visible_answer_fallback() -> None:
    chat_models = (FRONTEND / "chatModels.ts").read_text(encoding="utf-8")
    assistant = (
        FRONTEND / "workspace" / "AssistantResponse.tsx"
    ).read_text(encoding="utf-8")

    assert "fallbackAnswer: turn.summary" in chat_models
    assert "view.fallbackAnswer" in assistant


def test_conversation_module_exposes_shared_normalize_and_merge_contract() -> None:
    conversations = (FRONTEND / "conversations.ts").read_text(encoding="utf-8")

    assert "export function normalizeConversations" in conversations
    assert "export function mergeConversations" in conversations
    assert "remote.updatedAt >= local.updatedAt" in conversations
