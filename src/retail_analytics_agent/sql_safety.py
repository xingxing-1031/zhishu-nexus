from sqlglot import exp, parse
from sqlglot.errors import ParseError


class SQLSafetyError(ValueError):
    """Raised when SQL is not a single read-only query."""


_READ_ONLY_ROOTS = (
    exp.Select,
    exp.Union,
    exp.Intersect,
    exp.Except,
)

_FORBIDDEN_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Into,
)


def validate_read_only_sql(sql: str) -> exp.Expression:
    """Parse one PostgreSQL SQL statement and allow only read-only queries."""
    if not sql.strip():
        raise SQLSafetyError("SQL must not be empty")

    try:
        statements = parse(sql, read="postgres")
    except ParseError as exc:
        raise SQLSafetyError("SQL could not be parsed") from exc

    if len(statements) != 1:
        raise SQLSafetyError("only one SQL statement is allowed")

    statement = statements[0]
    if statement is None or not isinstance(statement, _READ_ONLY_ROOTS):
        raise SQLSafetyError(
            "only read-only SELECT statements are allowed"
        )

    forbidden = next(
        (node for node in statement.walk() if isinstance(node, _FORBIDDEN_NODES)),
        None,
    )
    if forbidden is not None:
        raise SQLSafetyError(
            f"SQL contains a forbidden operation: {type(forbidden).__name__}"
        )

    return statement
