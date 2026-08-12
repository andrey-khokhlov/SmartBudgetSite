import importlib.util
from pathlib import Path
from unittest.mock import patch


def load_migration():
    path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "7c2a4e8f91b0_add_active_service_addon_identity.py"
    )
    spec = importlib.util.spec_from_file_location("service_addon_identity_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_migration_creates_currency_aware_active_identity_index():
    migration = load_migration()

    with patch.object(migration.op, "create_index") as create_index:
        migration.upgrade()

    create_index.assert_called_once()
    args = create_index.call_args.args
    kwargs = create_index.call_args.kwargs
    assert args == (
        "uq_service_addons_active_business_identity",
        "service_addons",
        [
            "family_slug",
            "package_code",
            "service_type",
            "usage_type",
            "currency_code",
        ],
    )
    assert kwargs["unique"] is True
    assert str(kwargs["postgresql_where"]).lower() == "is_active = true"
