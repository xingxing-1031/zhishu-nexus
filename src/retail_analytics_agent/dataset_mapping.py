from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from retail_analytics_agent.dataset_models import SchemaProfile


class MappingRole(StrEnum):
    ORDER_ID = "order_id"
    PRODUCT_ID = "product_id"
    AMOUNT = "amount"
    QUANTITY = "quantity"
    CHANNEL = "channel"
    CATEGORY = "category"
    REGION = "region"
    STATUS = "status"
    TIME = "time"


class MappingField(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: MappingRole
    table: str = Field(min_length=1, max_length=63)
    column: str = Field(min_length=1, max_length=63)
    confidence: float = Field(ge=0, le=1)
    reasons: tuple[str, ...] = ()


class DatasetMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str = Field(min_length=1, max_length=80)
    version: int = Field(ge=1)
    mapping_version: str = Field(default="v1", pattern=r"^v[1-9][0-9]*$")
    fields: tuple[MappingField, ...] = Field(default=(), max_length=30)
    confirmed: bool = False

    @model_validator(mode="after")
    def validate_unique_fields(self) -> "DatasetMapping":
        roles = [field.role for field in self.fields]
        sources = [(field.table, field.column) for field in self.fields]
        if len(set(roles)) != len(roles):
            raise ValueError("mapping roles must be unique")
        if len(set(sources)) != len(sources):
            raise ValueError("mapping source columns must be unique")
        return self


class MappingValidationError(ValueError):
    """Raised when a proposed mapping cannot be applied to a SchemaProfile."""


_ROLE_SYNONYMS: dict[MappingRole, tuple[str, ...]] = {
    MappingRole.ORDER_ID: ("order_id", "order_no", "订单", "订单编号"),
    MappingRole.PRODUCT_ID: ("product_id", "sku", "商品", "商品编号"),
    MappingRole.AMOUNT: (
        "amount",
        "total_amount",
        "sales",
        "revenue",
        "price",
        "金额",
        "销售额",
    ),
    MappingRole.QUANTITY: ("quantity", "qty", "units", "销量", "数量"),
    MappingRole.CHANNEL: ("channel", "渠道", "source"),
    MappingRole.CATEGORY: ("category", "品类", "类别"),
    MappingRole.REGION: ("region", "地区", "区域"),
    MappingRole.STATUS: ("status", "状态"),
    MappingRole.TIME: ("date", "time", "created", "updated", "日期", "时间"),
}


def propose_mapping(
    dataset_id: str,
    version: int,
    profile: SchemaProfile,
) -> DatasetMapping:
    fields: list[MappingField] = []
    used_sources: set[tuple[str, str]] = set()
    used_roles: set[MappingRole] = set()
    for table in profile.tables:
        for column in table.columns:
            matches = _column_matches(column.name, column.candidate_roles)
            for role, confidence, reason in matches:
                source = (table.table_name, column.name)
                if role in used_roles or source in used_sources:
                    continue
                fields.append(
                    MappingField(
                        role=role,
                        table=table.table_name,
                        column=column.name,
                        confidence=confidence,
                        reasons=(reason,),
                    )
                )
                used_roles.add(role)
                used_sources.add(source)
                break
    return DatasetMapping(
        dataset_id=dataset_id,
        version=version,
        fields=tuple(fields),
        confirmed=False,
    )


def validate_mapping(
    mapping: DatasetMapping,
    profile: SchemaProfile,
) -> DatasetMapping:
    if mapping.dataset_id and mapping.version < 1:
        raise MappingValidationError("mapping version is invalid")
    tables = {table.table_name: table for table in profile.tables}
    for field in mapping.fields:
        table = tables.get(field.table)
        if table is None:
            raise MappingValidationError(f"table does not exist: {field.table}")
        columns = {column.name: column for column in table.columns}
        column = columns.get(field.column)
        if column is None:
            raise MappingValidationError(f"column does not exist: {field.column}")
        if not _role_compatible(field.role, column.normalized_type, column.candidate_roles):
            raise MappingValidationError(
                f"mapping is incompatible with column: {field.role.value} -> {field.column}"
            )
    return mapping


def _column_matches(
    name: str,
    candidate_roles: tuple[str, ...],
) -> tuple[tuple[MappingRole, float, str], ...]:
    lowered = name.casefold()
    matches: list[tuple[MappingRole, float, str]] = []
    for role, synonyms in _ROLE_SYNONYMS.items():
        normalized_synonyms = tuple(item.casefold() for item in synonyms)
        if lowered in normalized_synonyms or any(
            synonym and synonym in lowered for synonym in normalized_synonyms
        ):
            matches.append((role, 0.95, "column name matches a known synonym"))
        elif role.value in candidate_roles:
            matches.append((role, 0.75, "SchemaProfiler candidate role"))
    return tuple(matches)


def _role_compatible(
    role: MappingRole,
    normalized_type: str,
    candidate_roles: tuple[str, ...],
) -> bool:
    if role is MappingRole.AMOUNT:
        return normalized_type in {"numeric", "integer", "float"} or "amount" in candidate_roles
    if role is MappingRole.QUANTITY:
        return normalized_type in {"integer", "numeric", "float"}
    if role is MappingRole.TIME:
        return normalized_type in {"date", "timestamp", "time"} or "time" in candidate_roles
    if role in {MappingRole.ORDER_ID, MappingRole.PRODUCT_ID}:
        return "identifier" in candidate_roles or normalized_type in {"text", "integer"}
    return normalized_type in {"text", "string", "integer", "numeric"} or "categorical" in candidate_roles
