import importlib.util
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.models.consultation_entitlement import ConsultationEntitlement
from app.models.product_price import ProductPrice

ACTIVE_PRICE_INDEX_NAME = "uq_product_price_active_per_currency"
CONSULTATION_TIMESTAMP_COLUMNS = ("created_at", "expires_at", "booked_at")


def _load_migration():
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "2f6a9d7c4e10_restore_db_schema_parity.py"
    )
    spec = importlib.util.spec_from_file_location(
        "restore_db_schema_parity_migration",
        migration_path,
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _active_price_index() -> sa.Index:
    product_price_table = ProductPrice.metadata.tables[ProductPrice.__tablename__]
    matching_indexes = [
        index
        for index in product_price_table.indexes
        if index.name == ACTIVE_PRICE_INDEX_NAME
    ]
    assert len(matching_indexes) == 1
    return matching_indexes[0]


def test_consultation_timestamps_are_timezone_aware_in_metadata() -> None:
    for column_name in CONSULTATION_TIMESTAMP_COLUMNS:
        column_type = ConsultationEntitlement.__table__.c[column_name].type
        assert isinstance(column_type, sa.DateTime)
        assert column_type.timezone is True


def test_product_price_metadata_declares_active_price_partial_unique_index() -> None:
    index = _active_price_index()

    assert index.unique is True
    assert [column.name for column in index.columns] == [
        "product_id",
        "currency_code",
    ]

    predicate = index.dialect_options["postgresql"]["where"]
    compiled_predicate = str(predicate.compile(dialect=postgresql.dialect()))
    assert compiled_predicate.lower() == "is_active = true"


def test_migration_interprets_naive_consultation_timestamps_as_utc() -> None:
    migration = _load_migration()

    with patch.object(migration.op, "alter_column") as alter_column:
        migration.upgrade()

    assert alter_column.call_count == 3
    for actual_call, (column_name, nullable) in zip(
        alter_column.call_args_list,
        (
            ("created_at", False),
            ("expires_at", False),
            ("booked_at", True),
        ),
        strict=True,
    ):
        assert actual_call.args == ("consultation_entitlements", column_name)
        assert actual_call.kwargs["existing_type"].timezone is False
        assert actual_call.kwargs["type_"].timezone is True
        assert actual_call.kwargs["existing_nullable"] is nullable
        assert (
            actual_call.kwargs["postgresql_using"]
            == f"{column_name} AT TIME ZONE 'UTC'"
        )


def test_migration_downgrade_restores_naive_utc_timestamps() -> None:
    migration = _load_migration()

    with patch.object(migration.op, "alter_column") as alter_column:
        migration.downgrade()

    assert alter_column.call_count == 3
    for actual_call, (column_name, nullable) in zip(
        alter_column.call_args_list,
        (
            ("created_at", False),
            ("expires_at", False),
            ("booked_at", True),
        ),
        strict=True,
    ):
        assert actual_call.args == ("consultation_entitlements", column_name)
        assert actual_call.kwargs["existing_type"].timezone is True
        assert actual_call.kwargs["type_"].timezone is False
        assert actual_call.kwargs["existing_nullable"] is nullable
        assert (
            actual_call.kwargs["postgresql_using"]
            == f"{column_name} AT TIME ZONE 'UTC'"
        )
