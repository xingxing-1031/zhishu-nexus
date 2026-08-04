import pytest
from sqlglot import exp

from retail_analytics_agent.models import AccessRole
from retail_analytics_agent.sql_safety import (
    SQLSafetyError,
    prepare_safe_sql,
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


def test_prepare_safe_sql_allows_business_fields_and_adds_limit() -> None:
    prepared = prepare_safe_sql(
        "SELECT order_id, amount FROM orders ORDER BY amount DESC",
        max_rows=25,
    )

    assert prepared.sql == (
        "SELECT order_id, amount FROM orders ORDER BY amount DESC LIMIT 25"
    )
    assert prepared.tables == ("orders",)
    assert prepared.max_rows == 25


def test_prepare_safe_sql_preserves_smaller_limit() -> None:
    prepared = prepare_safe_sql(
        "SELECT order_id FROM orders LIMIT 5",
        max_rows=20,
    )

    assert prepared.sql.endswith("LIMIT 5")


def test_prepare_safe_sql_caps_larger_limit() -> None:
    prepared = prepare_safe_sql(
        "SELECT order_id FROM orders LIMIT 500",
        max_rows=20,
    )

    assert prepared.sql.endswith("LIMIT 20")


def test_prepare_safe_sql_allows_count_star_and_projection_alias() -> None:
    prepared = prepare_safe_sql(
        "SELECT channel, COUNT(*) AS order_count "
        "FROM orders GROUP BY channel ORDER BY order_count DESC"
    )

    assert "COUNT(*) AS order_count" in prepared.sql


def test_prepare_safe_sql_allows_approved_join_fields() -> None:
    prepared = prepare_safe_sql(
        "SELECT o.order_id, p.name "
        "FROM orders AS o "
        "JOIN order_items AS oi ON oi.order_id = o.order_id "
        "JOIN products AS p ON p.product_id = oi.product_id"
    )

    assert prepared.tables == ("order_items", "orders", "products")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT reason FROM refunds",
        "SELECT r.reason FROM refunds AS r",
        (
            "WITH refund_reasons AS ("
            "SELECT reason FROM refunds"
            ") SELECT reason FROM refund_reasons"
        ),
    ],
)
def test_analyst_cannot_read_refund_reason_through_alias_or_cte(
    sql: str,
) -> None:
    with pytest.raises(
        SQLSafetyError,
        match="role analyst is not allowed to access column: refunds.reason",
    ):
        prepare_safe_sql(sql, access_role=AccessRole.ANALYST)


def test_admin_can_read_refund_reason_and_role_is_preserved() -> None:
    prepared = prepare_safe_sql(
        "SELECT reason FROM refunds",
        access_role=AccessRole.ADMIN,
    )

    assert prepared.sql == "SELECT reason FROM refunds LIMIT 100"
    assert prepared.access_role is AccessRole.ADMIN


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM orders",
        "UPDATE orders SET amount = 0",
    ],
)
def test_admin_role_does_not_bypass_read_only_policy(sql: str) -> None:
    with pytest.raises(
        SQLSafetyError,
        match="only read-only SELECT statements are allowed",
    ):
        prepare_safe_sql(sql, access_role=AccessRole.ADMIN)


@pytest.mark.parametrize(
    ("sql", "message"),
    [
        ("SELECT order_id FROM company_salary", "table is not allowed"),
        ("SELECT secret_note FROM orders", "column is not allowed"),
        ("SELECT * FROM orders", "wildcard columns are not allowed"),
        (
            "SELECT order_id FROM private.orders",
            "table is outside the allowed schema",
        ),
        ("SELECT pg_sleep(60)", "function is not allowed: pg_sleep"),
    ],
)
def test_prepare_safe_sql_rejects_policy_violations(
    sql: str,
    message: str,
) -> None:
    with pytest.raises(SQLSafetyError, match=message):
        prepare_safe_sql(sql)


@pytest.mark.parametrize("max_rows", [0, 1001])
def test_prepare_safe_sql_rejects_invalid_max_rows(max_rows: int) -> None:
    with pytest.raises(
        SQLSafetyError,
        match="max_rows must be between 1 and 1000",
    ):
        prepare_safe_sql("SELECT order_id FROM orders", max_rows=max_rows)
