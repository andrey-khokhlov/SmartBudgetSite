import importlib.util
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa


def _load_migration():
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "f6d2c8a91e34_add_feedback_created_at_default.py"
    )
    spec = importlib.util.spec_from_file_location(
        "feedback_created_at_default_migration",
        migration_path,
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_upgrade_sets_feedback_created_at_server_default() -> None:
    migration = _load_migration()

    with patch.object(migration.op, "alter_column") as alter_column:
        migration.upgrade()

    alter_column.assert_called_once()
    args, kwargs = alter_column.call_args
    assert args == ("feedback_messages", "created_at")
    assert isinstance(kwargs["existing_type"], sa.DateTime)
    assert kwargs["existing_type"].timezone is True
    assert kwargs["existing_nullable"] is False
    assert str(kwargs["server_default"]) == "now()"


def test_downgrade_removes_only_feedback_created_at_server_default() -> None:
    migration = _load_migration()

    with patch.object(migration.op, "alter_column") as alter_column:
        migration.downgrade()

    alter_column.assert_called_once()
    args, kwargs = alter_column.call_args
    assert args == ("feedback_messages", "created_at")
    assert isinstance(kwargs["existing_type"], sa.DateTime)
    assert kwargs["existing_type"].timezone is True
    assert kwargs["existing_nullable"] is False
    assert kwargs["server_default"] is None
