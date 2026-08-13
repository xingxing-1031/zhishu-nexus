import pytest
from pydantic import ValidationError

from retail_analytics_agent.knowledge_chunks import (
    DEFAULT_KNOWLEDGE_CORPUS,
    KnowledgeChunk,
    KnowledgeCorpus,
    KnowledgeType,
)


def test_default_corpus_uses_business_semantic_boundaries() -> None:
    chunks = DEFAULT_KNOWLEDGE_CORPUS.chunks

    assert len(chunks) == 14
    assert sum(item.knowledge_type is KnowledgeType.METRIC for item in chunks) == 7
    assert sum(item.knowledge_type is KnowledgeType.TABLE for item in chunks) == 4
    assert sum(item.knowledge_type is KnowledgeType.JOIN for item in chunks) == 3
    assert any(item.source_id == "metric.refund_rate.v1" for item in chunks)


def test_sales_metric_chunk_keeps_the_complete_business_definition() -> None:
    chunk = next(
        item
        for item in DEFAULT_KNOWLEDGE_CORPUS.chunks
        if item.source_id == "metric.sales_amount.v1"
    )

    assert chunk.version == "v1"
    assert chunk.related_tables == ("orders", "order_items")
    assert "order_items.quantity * order_items.unit_price" in chunk.content
    assert "orders.status equals paid" in chunk.content
    assert "Supported dimensions: channel, product, category, day" in chunk.content


def test_table_and_join_chunks_keep_retrieval_metadata() -> None:
    table = next(
        item
        for item in DEFAULT_KNOWLEDGE_CORPUS.chunks
        if item.source_id == "schema.products"
    )
    join = next(
        item
        for item in DEFAULT_KNOWLEDGE_CORPUS.chunks
        if item.source_id == "schema.join.products.order_items"
    )

    assert table.knowledge_type is KnowledgeType.TABLE
    assert table.related_tables == ("products",)
    assert table.version is None
    assert join.knowledge_type is KnowledgeType.JOIN
    assert join.related_tables == ("products", "order_items")
    assert "products.product_id = order_items.product_id" in join.content


def test_chunk_can_return_the_existing_workflow_evidence_contract() -> None:
    chunk = DEFAULT_KNOWLEDGE_CORPUS.chunks[0]

    evidence = chunk.to_evidence()

    assert evidence.source_id == chunk.source_id
    assert evidence.content == chunk.content


def test_chunk_rejects_inconsistent_identity_metadata() -> None:
    with pytest.raises(ValidationError, match="source_id must start with metric"):
        KnowledgeChunk(
            source_id="schema.orders",
            knowledge_type="metric",
            content="orders",
            version="v1",
            related_tables=("orders",),
        )

    with pytest.raises(ValidationError, match="metric chunks require a version"):
        KnowledgeChunk(
            source_id="metric.sales_amount.v1",
            knowledge_type="metric",
            content="sales",
            related_tables=("orders",),
        )


def test_corpus_rejects_duplicate_source_ids() -> None:
    chunk = DEFAULT_KNOWLEDGE_CORPUS.chunks[0]

    with pytest.raises(ValidationError, match="source_id values must be unique"):
        KnowledgeCorpus(
            corpus_id="duplicate-corpus",
            chunks=(chunk, chunk),
        )
