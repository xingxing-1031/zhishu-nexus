import httpx

from retail_analytics_agent.database import connect_to_database
from retail_analytics_agent.embeddings import (
    OllamaEmbeddingProvider,
    embed_knowledge_corpus,
)
from retail_analytics_agent.knowledge_chunks import DEFAULT_KNOWLEDGE_CORPUS
from retail_analytics_agent.knowledge_store import upsert_embedded_corpus

OLLAMA_BASE_URL = "http://127.0.0.1:11434"
EMBEDDING_MODEL = "bge-m3"


def main() -> None:
    with httpx.Client(base_url=OLLAMA_BASE_URL, timeout=120) as client:
        provider = OllamaEmbeddingProvider(client=client, model=EMBEDDING_MODEL)
        corpus = embed_knowledge_corpus(provider, DEFAULT_KNOWLEDGE_CORPUS)

    with connect_to_database() as connection:
        indexed_count = upsert_embedded_corpus(connection, corpus)

    print(
        f"Indexed {indexed_count} knowledge chunks with "
        f"{corpus.embedding_model} ({corpus.vector_dimension} dimensions)."
    )


if __name__ == "__main__":
    main()
