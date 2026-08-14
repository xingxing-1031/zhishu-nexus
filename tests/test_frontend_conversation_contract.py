import json
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


def test_conversation_module_exposes_server_snapshot_reconciliation() -> None:
    conversations = (FRONTEND / "conversations.ts").read_text(encoding="utf-8")

    assert "export function reconcileConversations" in conversations
    assert "remoteConversations" in conversations
    assert "turns.length === 0" in conversations


def test_conversation_sync_refreshes_visible_accounts_and_preserves_pending_deletes() -> None:
    sync = (FRONTEND / "useConversationSync.ts").read_text(encoding="utf-8")

    assert "reconcileConversations" in sync
    assert "setInterval" in sync
    assert "5_000" in sync
    assert "pendingDeletesRef.current.has" in sync
    interval_block = sync.split("const timer = window.setInterval(() =>", maxsplit=1)[1].split("},", maxsplit=1)[0]
    assert "document.visibilityState" not in interval_block


def test_mobile_conversation_delete_action_is_not_hidden_by_hover_state() -> None:
    styles = (FRONTEND / "styles.css").read_text(encoding="utf-8")

    assert ".rail-conversation > button:last-child {" in styles
    delete_rule = styles.split(".rail-conversation > button:last-child {", maxsplit=1)[1].split("}", maxsplit=1)[0]
    assert "opacity: 0" not in delete_rule


def test_zhishu_brand_is_consistent_across_active_workspace() -> None:
    root = Path(__file__).parents[1]
    login = (FRONTEND / "LoginPage.tsx").read_text(encoding="utf-8")
    assistant = (
        FRONTEND / "workspace" / "AssistantResponse.tsx"
    ).read_text(encoding="utf-8")
    brand = (FRONTEND / "brand.tsx").read_text(encoding="utf-8")
    package = json.loads(
        (root / "frontend" / "package.json").read_text(encoding="utf-8")
    )

    assert "把企业问题交给知枢" in login
    assert 'assistantName: "知枢 AI"' in brand
    assert package["name"] == "zhishu-nexus-console"
    assert ">析<" not in login + assistant
