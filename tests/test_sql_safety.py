import pytest
from sqlglot import exp

from retail_analytics_agent.sql_safety import (
    SQLSafetyError,
    validate_read_only_sql,
)


def test_validate_read_only_sql_returns_select_ast() -> None:
    statement = validate_read_only_sql(
        "SELECT channel, COUNT(*) FROM orders GROUP BY channel"
    )

    assert isinstance(statement, exp.Select)
    assert statement.sql(dialect="postgres") == (
        "SELECT channel, COUNT(*) FROM orders GROUP BY channel"
    )


def test_validate_read_only_sql_allows_cte_and_union() -> None:
    cte = validate_read_only_sql(
        "WITH recent AS (SELECT * FROM orders) "
        "SELECT * FROM recent"
    )
    union = validate_read_only_sql("SELECT 1 UNION SELECT 2")

    assert isinstance(cte, exp.Select)
    assert isinstance(union, exp.Union)


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO orders (order_id) VALUES ('ORD-NEW')",
        "UPDATE orders SET amount = 0",
        "DELETE FROM orders",
        "CREATE TABLE audit_log (id INT)",
        "DROP TABLE orders",
        "ALTER TABLE orders ADD COLUMN note TEXT",
        "TRUNCATE orders",
    ],
)
def test_validate_read_only_sql_rejects_write_and_ddl(sql: str) -> None:
    with pytest.raises(
        SQLSafetyError,
        match="only read-only SELECT statements are allowed",
    ):
        validate_read_only_sql(sql)


def test_validate_read_only_sql_rejects_multiple_statements() -> None:
    with pytest.raises(
        SQLSafetyError,
        match="only one SQL statement is allowed",
    ):
        validate_read_only_sql("SELECT 1; DROP TABLE orders")


def test_validate_read_only_sql_rejects_select_into() -> None:
    with pytest.raises(
        SQLSafetyError,
        match="forbidden operation: Into",
    ):
        validate_read_only_sql("SELECT * INTO exported_orders FROM orders")


def test_validate_read_only_sql_rejects_write_hidden_in_cte() -> None:
    with pytest.raises(
        SQLSafetyError,
        match="forbidden operation: Delete",
    ):
        validate_read_only_sql(
            "WITH deleted AS (DELETE FROM orders RETURNING *) "
            "SELECT * FROM deleted"
        )


def test_validate_read_only_sql_rejects_empty_sql() -> None:
    with pytest.raises(SQLSafetyError, match="SQL must not be empty"):
        validate_read_only_sql("  \n  ")
