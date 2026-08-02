from retail_analytics_agent.database import connect_to_database


SCHEMA_VERIFICATION_SQL = """
SELECT
    format_type(attribute.atttypid, attribute.atttypmod) AS vector_type,
    (SELECT COUNT(*) FROM knowledge_chunks) AS row_count,
    EXISTS (
        SELECT 1
        FROM pg_extension
        WHERE extname = 'vector'
    ) AS vector_enabled
FROM pg_attribute AS attribute
WHERE attribute.attrelid = 'knowledge_chunks'::regclass
  AND attribute.attname = 'embedding';
"""


def main() -> None:
    with connect_to_database() as connection:
        row = connection.execute(SCHEMA_VERIFICATION_SQL).fetchone()

    if row is None:
        raise AssertionError("knowledge_chunks.embedding is missing")
    if row["vector_type"] != "vector(1024)":
        raise AssertionError(
            f"unexpected embedding type: {row['vector_type']}"
        )
    if row["vector_enabled"] is not True:
        raise AssertionError("pgvector extension is not enabled")

    print(
        "W4-3 knowledge schema verification passed: "
        f"{row['vector_type']}, {row['row_count']} rows"
    )


if __name__ == "__main__":
    main()
