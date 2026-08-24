from __future__ import annotations

import pytest

from retail_analytics_agent.dataset_mapping import (
    DatasetMapping,
    MappingField,
    MappingRole,
    MappingValidationError,
    propose_mapping,
    validate_mapping,
)
from retail_analytics_agent.dataset_models import (
    ColumnProfile,
    SchemaProfile,
    TableProfile,
)


def _profile() -> SchemaProfile:
    return SchemaProfile(
        schema_name="staging_demo_1",
        tables=(
            TableProfile(
                table_name="dataset_rows",
                row_count=2,
                columns=(
                    ColumnProfile(
                        name="order_id",
                        normalized_type="text",
                        null_ratio=0,
                        unique_ratio=1,
                        candidate_roles=("identifier",),
                    ),
                    ColumnProfile(
                        name="total_amount",
                        normalized_type="numeric",
                        null_ratio=0,
                        unique_ratio=1,
                        candidate_roles=("amount",),
                    ),
                    ColumnProfile(
                        name="sales_channel",
                        normalized_type="text",
                        null_ratio=0,
                        unique_ratio=0.5,
                        candidate_roles=("categorical",),
                    ),
                    ColumnProfile(
                        name="ordered_at",
                        normalized_type="timestamp",
                        null_ratio=0,
                        unique_ratio=1,
                        candidate_roles=("time",),
                    ),
                ),
            ),
        ),
    )


def test_proposal_maps_common_sales_columns_without_claiming_confirmation() -> None:
    proposal = propose_mapping("demo", 1, _profile())

    assert proposal.confirmed is False
    assert proposal.dataset_id == "demo"
    assert {item.role for item in proposal.fields} >= {
        MappingRole.ORDER_ID,
        MappingRole.AMOUNT,
        MappingRole.CHANNEL,
        MappingRole.TIME,
    }
    amount = next(item for item in proposal.fields if item.role is MappingRole.AMOUNT)
    assert amount.column == "total_amount"
    assert amount.confidence >= 0.8


def test_mapping_validation_rejects_unknown_column_and_incompatible_type() -> None:
    mapping = DatasetMapping(
        dataset_id="demo",
        version=1,
        fields=(
            MappingField(
                role=MappingRole.AMOUNT,
                table="dataset_rows",
                column="missing_amount",
                confidence=1,
            ),
        ),
    )

    with pytest.raises(MappingValidationError, match="column does not exist"):
        validate_mapping(mapping, _profile())

    incompatible = mapping.model_copy(
        update={
            "fields": (
                MappingField(
                    role=MappingRole.AMOUNT,
                    table="dataset_rows",
                    column="sales_channel",
                    confidence=1,
                ),
            )
        }
    )
    with pytest.raises(MappingValidationError, match="incompatible"):
        validate_mapping(incompatible, _profile())


def test_mapping_validation_rejects_duplicate_roles_and_source_columns() -> None:
    with pytest.raises(ValueError, match="roles must be unique"):
        DatasetMapping(
            dataset_id="demo",
            version=1,
            fields=(
                MappingField(
                    role=MappingRole.CHANNEL,
                    table="dataset_rows",
                    column="sales_channel",
                    confidence=0.8,
                ),
                MappingField(
                    role=MappingRole.CHANNEL,
                    table="dataset_rows",
                    column="sales_channel",
                    confidence=0.7,
                ),
            ),
        )

