from collections.abc import Collection, Mapping

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
    referenced_columns: tuple[str, ...] = ()
    result_limit: int = Field(default=100, ge=1, le=MAX_QUERY_ROWS)


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
    allowed_columns: Mapping[str, Collection[str]] | None = None,
    allowed_schema: str | None = None,
) -> PreparedSQL:
    """Validate a generated query and enforce its maximum result size.

    ``allowed_columns`` and ``allowed_schema`` narrow the query to one dataset;
    when omitted the fixed public demo tables and public schema are used.
    """
    if not 1 <= max_rows <= MAX_QUERY_ROWS:
        raise SQLSafetyError(
            f"max_rows must be between 1 and {MAX_QUERY_ROWS}"
        )

    effective_columns = dict(
        _ALLOWED_COLUMNS if allowed_columns is None else allowed_columns
    )
    statement = validate_read_only_sql(sql)
    tables, aliases, derived_relations = _validate_tables(
        statement,
        effective_columns,
        allowed_schema,
    )
    _validate_columns(
        statement,
        tables,
        aliases,
        derived_relations,
        effective_columns,
    )
    referenced_columns = _collect_referenced_columns(
        statement,
        tables,
        aliases,
        effective_columns,
    )
    _validate_role_columns(referenced_columns, access_role)
    _validate_functions(statement)

    limited_statement = _enforce_limit(statement, max_rows)
    result_limit = _read_result_limit(limited_statement)
    return PreparedSQL(
        sql=limited_statement.sql(dialect="postgres"),
        tables=tuple(sorted(tables)),
        max_rows=max_rows,
        access_role=access_role,
        referenced_columns=tuple(sorted(referenced_columns)),
        result_limit=result_limit,
    )


def _validate_role_columns(
    referenced_columns: set[str],
    access_role: AccessRole,
) -> None:
    denied = denied_columns_for_role(access_role)
    if not denied:
        return

    denied_names = {f"{table}.{column}" for table, column in denied}
    forbidden = sorted(referenced_columns & denied_names)
    if forbidden:
        raise SQLSafetyError(
            f"role {access_role.value} is not allowed to access column: "
            f"{forbidden[0]}"
        )


def _collect_referenced_columns(
    statement: exp.Expression,
    tables: set[str],
    aliases: dict[str, str],
    allowed_columns: Mapping[str, Collection[str]],
) -> set[str]:
    referenced: set[str] = set()
    for column in statement.find_all(exp.Column):
        column_name = column.name.lower()
        if column_name == "*":
            continue

        qualifier = column.table.lower() if column.table else ""
        if qualifier:
            table_name = aliases.get(qualifier)
            if table_name is not None:
                referenced.add(f"{table_name}.{column_name}")
            continue

        for table_name in tables:
            if column_name in allowed_columns[table_name]:
                referenced.add(f"{table_name}.{column_name}")
    return referenced


def _validate_tables(
    statement: exp.Expression,
    allowed_columns: Mapping[str, Collection[str]],
    allowed_schema: str | None = None,
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

    accepted_schemas = (
        {"", "public"} if allowed_schema is None else {allowed_schema}
    )
    for table in statement.find_all(exp.Table):
        table_name = table.name.lower()
        if table_name in cte_names:
            continue

        schema_name = table.db.lower() if table.db else ""
        if table.catalog or schema_name not in accepted_schemas:
            raise SQLSafetyError(
                f"table is outside the allowed schema: {table.sql()}"
            )

        if table_name not in allowed_columns:
            raise SQLSafetyError(f"table is not allowed: {table_name}")

        tables.add(table_name)
        aliases[table.alias_or_name.lower()] = table_name

    return tables, aliases, derived_relations


def _validate_columns(
    statement: exp.Expression,
    tables: set[str],
    aliases: dict[str, str],
    derived_relations: set[str],
    allowed_columns: Mapping[str, Collection[str]],
) -> None:
    for star in statement.find_all(exp.Star):
        if not _is_count_star(star):
            raise SQLSafetyError(
                "wildcard columns are not allowed; list fields explicitly"
            )

    allowed_unqualified = (
        set().union(*(allowed_columns[table] for table in tables))
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
        if column_name not in allowed_columns[table_name]:
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


def _read_result_limit(statement: exp.Expression) -> int:
    limit = statement.args.get("limit")
    if not isinstance(limit, exp.Limit):
        raise SQLSafetyError("validated SQL must contain a result limit")
    expression = limit.expression
    if not isinstance(expression, exp.Literal) or not expression.is_int:
        raise SQLSafetyError("validated SQL must use an integer result limit")
    return int(expression.this)
