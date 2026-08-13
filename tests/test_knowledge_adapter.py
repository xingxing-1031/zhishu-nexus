from datetime import date

import httpx
import pytest

from retail_analytics_agent.knowledge_adapter import (
    FixtureKnowledgeAdapter,
    HttpKnowledgeAdapter,
    KnowledgeAdapterError,
    KnowledgeEvidence,
    KnowledgeQuery,
    evidence_to_tool_payload,
)


def _query() -> KnowledgeQuery:
    return KnowledgeQuery(query="退款制度", user_id="u1", role="analyst", top_k=2)


def test_fixture_adapter_returns_bounded_governed_evidence() -> None:
    adapter = FixtureKnowledgeAdapter((
        KnowledgeEvidence(
            source_id="policy:refund:v1", title="退款制度", version="v1",
            effective_from=date(2026, 1, 1), quote="退款需在七日内申请", score=0.9,
            permissions=("analyst",),
        ),
    ))
    result = adapter.retrieve(_query())
    assert result[0].source_id == "policy:refund:v1"
    assert evidence_to_tool_payload(result)["evidence_ids"] == ["policy:refund:v1"]


def test_http_adapter_validates_response_and_preserves_source_id() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        "evidence": [{
            "source_id": "policy:refund:v2", "title": "售后制度", "version": "v2",
            "quote": "高退款率需复核", "score": 0.88, "permissions": ["analyst"],
        }],
    }))
    adapter = HttpKnowledgeAdapter("http://rag.test", httpx.Client(transport=transport))
    assert adapter.retrieve(_query())[0].source_id == "policy:refund:v2"


def test_http_adapter_fails_closed_on_malformed_response() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"answer": "only text"}))
    adapter = HttpKnowledgeAdapter("http://rag.test", httpx.Client(transport=transport))
    assert adapter.retrieve(_query()) == ()


def test_http_adapter_rejects_unavailable_service() -> None:
    transport = httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.ConnectError("offline")))
    adapter = HttpKnowledgeAdapter("http://rag.test", httpx.Client(transport=transport))
    with pytest.raises(KnowledgeAdapterError, match="unavailable"):
        adapter.retrieve(_query())


def test_http_adapter_rejects_non_http_endpoint() -> None:
    adapter = HttpKnowledgeAdapter("file:///tmp/rag", httpx.Client())
    with pytest.raises(KnowledgeAdapterError, match="HTTP"):
        adapter.retrieve(_query())
