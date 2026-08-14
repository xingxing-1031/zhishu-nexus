from datetime import datetime, timedelta, timezone

from retail_analytics_agent.workspace_history import (
    InMemoryWorkspaceHistoryStore,
    WorkspaceConversationPayload,
)


def _conversation(
    conversation_id: str,
    *,
    updated_at: datetime | None = None,
    turn_count: int = 1,
) -> WorkspaceConversationPayload:
    updated = updated_at or datetime.now(timezone.utc)
    return WorkspaceConversationPayload.model_validate(
        {
            "id": conversation_id,
            "title": f"会话 {conversation_id}",
            "createdAt": (updated - timedelta(minutes=1)).isoformat(),
            "updatedAt": updated.isoformat(),
            "turns": [
                {
                    "id": f"TURN-{index}",
                    "requestId": f"REQ-{conversation_id}-{index}",
                    "question": f"问题 {index}",
                    "createdAt": updated.isoformat(),
                    "durationMs": 120,
                    "status": "answered",
                    "summary": f"回答 {index}",
                    "outcome": None,
                    "response": None,
                    "chartSpec": None,
                    "rows": [],
                    "stageState": {},
                    "followUpContext": None,
                }
                for index in range(turn_count)
            ],
        }
    )


def test_workspace_history_isolates_fixed_demo_identities() -> None:
    store = InMemoryWorkspaceHistoryStore()
    analyst = _conversation("CONV-SHARED")
    admin = analyst.model_copy(update={"title": "管理员会话"})

    store.put("ANALYST-001", analyst)
    store.put("ADMIN-001", admin)

    assert store.list_for_user("ANALYST-001") == (analyst,)
    assert store.list_for_user("ADMIN-001") == (admin,)


def test_workspace_history_upserts_and_orders_recent_conversations() -> None:
    store = InMemoryWorkspaceHistoryStore()
    now = datetime.now(timezone.utc)
    older = _conversation("CONV-OLD", updated_at=now - timedelta(minutes=2))
    newer = _conversation("CONV-NEW", updated_at=now)

    store.put("ANALYST-001", older)
    store.put("ANALYST-001", newer)
    revised = older.model_copy(update={"title": "更新后的标题", "updated_at": now})
    store.put("ANALYST-001", revised)

    records = store.list_for_user("ANALYST-001")

    assert len(records) == 2
    assert records[0].title == "更新后的标题"
    assert {record.id for record in records} == {"CONV-OLD", "CONV-NEW"}


def test_workspace_history_bounds_conversations_and_turns() -> None:
    store = InMemoryWorkspaceHistoryStore(max_conversations=8, max_turns=8)
    now = datetime.now(timezone.utc)
    for index in range(10):
        store.put(
            "ANALYST-001",
            _conversation(
                f"CONV-{index}",
                updated_at=now + timedelta(minutes=index),
                turn_count=10,
            ),
        )

    records = store.list_for_user("ANALYST-001")

    assert len(records) == 8
    assert records[0].id == "CONV-9"
    assert records[-1].id == "CONV-2"
    assert all(len(record.turns) == 8 for record in records)


def test_workspace_history_delete_is_scoped_and_idempotent() -> None:
    store = InMemoryWorkspaceHistoryStore()
    conversation = _conversation("CONV-SHARED")
    store.put("ANALYST-001", conversation)
    store.put("ADMIN-001", conversation)

    assert store.delete("ANALYST-001", "CONV-SHARED") is True
    assert store.delete("ANALYST-001", "CONV-SHARED") is False
    assert store.list_for_user("ANALYST-001") == ()
    assert store.list_for_user("ADMIN-001") == (conversation,)
