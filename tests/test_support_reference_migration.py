import importlib.util
from pathlib import Path

from app.models.download_entitlement import DownloadEntitlement
from app.models.feedback import FeedbackMessage


def test_support_reference_model_contract():
    assert FeedbackMessage.__table__.c.type.type.length == 50
    assert FeedbackMessage.__table__.c.support_reference.nullable is True
    assert FeedbackMessage.__table__.c.support_reference.type.length == 64
    assert DownloadEntitlement.__table__.c.support_reference.nullable is False
    assert DownloadEntitlement.__table__.c.support_reference.type.length == 11
    assert DownloadEntitlement.__table__.c.support_reference.unique is True


def test_migration_backfill_generator_produces_unique_valid_references():
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "a47d9c2e6b10_add_feedback_support_references.py"
    )
    spec = importlib.util.spec_from_file_location(
        "support_reference_migration",
        migration_path,
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    existing: set[str] = set()

    first = migration._generate_support_reference(existing)
    second = migration._generate_support_reference(existing)

    assert first.startswith("DL-")
    assert len(first) == 11
    assert second.startswith("DL-")
    assert len(second) == 11
    assert first != second
