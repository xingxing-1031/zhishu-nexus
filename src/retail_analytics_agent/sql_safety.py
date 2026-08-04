from pydantic import BaseModel, ConfigDict, Field
from sqlglot import exp, parse
from sqlglot.errors import ParseError

from retail_analytics_agent.access_control import denied_columns_for_role
from retail_analytics_agent.models import AccessRole


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

_ALLOWED_COLUMNS = {
    "orders": frozenset(
        {"order_id", "channel", "amount", "status", "created_at"}
    ),
    "products": frozenset(
        {"product_id", "name", "category", "unit_price"}
    ),
    "order_items": frozenset(
        {
            "order_item_id",
            "order_id",
            "product_id",
            "quantity",
            "unit_price",
        }
    ),
    "refunds": frozenset(
        {
            "refund_id",
            "order_id",
            "refund_amount",
            "reason",
            "status",
            "created_at",
        }
    ),
}

_FORBIDDEN_FUNCTIONS = frozenset(
    {
        "dblink",
        "lo_export",
        "lo_import",
        "pg_ls_dir",
        "pg_read_binary_file",
        "pg_read_file",
        "pg_sleep",
    }
)

MAX_QUERY_ROWS = 1000


class PreparedSQL(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sql: str
    tables: tuple[str, ...]
    max_rows: int = Field(ge=1, le=MAX_QUERY_ROWS)
    access_role: AccessRole = AccessRole.ANALYST


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


def prepare_safe_sql(
    sql: str,
    max_rows: int = 100,
    *,
    access_role: AccessRole = AccessRole.ANALYST,
) -> PreparedSQL:
    """Validate a generated query and enforce its maximum result size."""
    if not 1 <= max_rows <= MAX_QUERY_ROWS:
        raise SQLSafetyError(
            f"max_rows must be between 1 and {MAX_QUERY_ROWS}"
        )

    statement = validate_read_only_sql(sql)
    tables, aliases, derived_relations = _validate_tables(statement)
    _validate_columns(statement, tables, aliases, derived_relations)
    _validate_role_columns(statement, tables, aliases, access_role)
    _validate_functions(statement)

    limited_statement = _enforce_limit(statement, max_rows)
    return PreparedSQL(
        sql=limited_statement.sql(dialect="postgres"),
        tables=tuple(sorted(tables)),
        max_rows=max_rows,
        access_role=access_role,
    )


def _validate_role_columns(
    statement: exp.Expression,
    tables: set[str],
    aliases: dict[str, str],
    access_role: AccessRole,
) -> None:
    denied = denied_columns_for_role(access_role)
    if not denied:
        return

    for column in statement.find_all(exp.Column):
        column_name = column.name.lower()
        qualifier = column.table.lower() if column.table else ""
        if qualifier:
            table_name = aliases.get(qualifier)
            if table_name is None:
                continue
            candidates = (table_name,)
        else:
            candidates = tuple(
                table_name
                for table_name in tables
                if column_name in _ALLOWED_COLUMNS[table_name]
            )

        for table_name in candidates:
            if (table_name, column_name) in denied:
                raise SQLSafetyError(
                    f"role {access_role.value} is not allowed to access "
                    f"column: {table_name}.{column_name}"
                )


def _validate_tables(
    statement: exp.Expression,
) -> tuple[set[str], dict[str, str], set[str]]:
    cte_names = {
        cte.alias_or_name.lower()
        for cte in statement.find_all(exp.CTE)
        if cte.alias_or_name
    }
    derived_relations = cte_names | {
        subquery.alias_or_name.lower()
        for subquery in statement.find_all(exp.Subquery)
        if subquery.alias_or_name
    }
    tables: set[str] = set()
    aliases: dict[str, str] = {}

    for table in statement.find_all(exp.Table):
        table_name = table.name.lower()
        if table_name in cte_names:
            continue

        schema_name = table.db.lower() if table.db else ""
        if table.catalog or schema_name not in {"", "public"}:
            raise SQLSafetyError(
                f"table is outside the allowed schema: {table.sql()}"
            )

        if table_name not in _ALLOWED_COLUMNS:
            raise SQLSafetyError(f"table is not allowed: {table_name}")

        tables.add(table_name)
        aliases[table.alias_or_name.lower()] = table_name

    return tables, aliases, derived_relations


def _validate_columns(
    statement: exp.Expression,
    tables: set[str],
    aliases: dict[str, str],
    derived_relations: set[str],
) -> None:
    for star in statement.find_all(exp.Star):
        if not _is_count_star(star):
            raise SQLSafetyError(
                "wildcard columns are not allowed; list fields explicitly"
            )

    allowed_unqualified = (
        set().union(*(_ALLOWED_COLUMNS[table] for table in tables))
        if tables
        else set()
    )
    projection_aliases = {
        alias.alias.lower()
        for alias in statement.find_all(exp.Alias)
        if alias.alias
    }
    allowed_derived_columns = allowed_unqualified | projection_aliases

    for column in statement.find_all(exp.Column):
        column_name = column.name.lower()
        if column_name == "*":
            continue

        qualifier = column.table.lower() if column.table else ""
        if not qualifier:
            if column_name not in allowed_derived_columns:
                raise SQLSafetyError(
                    f"column is not allowed: {column_name}"
                )
            continue

        if qualifier in derived_relations:
            if column_name not in allowed_derived_columns:
                raise SQLSafetyError(
                    f"column is not allowed: {qualifier}.{column_name}"
                )
            continue

        table_name = aliases.get(qualifier)
        if table_name is None:
            raise SQLSafetyError(f"unknown table alias: {qualifier}")
        if column_name not in _ALLOWED_COLUMNS[table_name]:
            raise SQLSafetyError(
                f"column is not allowed: {qualifier}.{column_name}"
            )


def _validate_functions(statement: exp.Expression) -> None:
    for function in statement.find_all(exp.Func):
        if isinstance(function, exp.Anonymous):
            function_name = function.name.lower()
        else:
            function_name = function.sql_name().lower()

        if function_name in _FORBIDDEN_FUNCTIONS:
            raise SQLSafetyError(
                f"function is not allowed: {function_name}"
            )


def _is_count_star(star: exp.Star) -> bool:
    parent = star.parent
    while parent is not None and not isinstance(parent, exp.Select):
        if isinstance(parent, exp.Count):
            return True
        parent = parent.parent
    return False


def _enforce_limit(
    statement: exp.Expression,
    max_rows: int,
) -> exp.Expression:
    limit = statement.args.get("limit")
    if isinstance(limit, exp.Limit):
        expression = limit.expression
        if isinstance(expression, exp.Literal) and expression.is_int:
            current_limit = int(expression.this)
            if 0 <= current_limit <= max_rows:
                return statement.copy()

    return statement.limit(max_rows, copy=True)
