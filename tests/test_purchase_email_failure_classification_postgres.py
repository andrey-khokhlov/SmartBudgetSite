import os
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.core.config import settings

PREVIOUS = "c20d9be51072"
REVISION = "78e0b9842bd1"


@pytest.fixture
def disposable_postgres():
    if os.environ.get("SMARTBUDGET_TEST_POSTGRES_MIGRATIONS") != "1":
        pytest.skip("Set SMARTBUDGET_TEST_POSTGRES_MIGRATIONS=1 for local PostgreSQL")
    base = make_url(settings.DATABASE_URL)
    assert base.get_backend_name() == "postgresql"
    assert base.host in {"localhost", "127.0.0.1", "::1"}
    name = f"email_classification_test_{uuid4().hex[:12]}"
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    url = base.set(database=name)
    engine = create_engine(url)
    try:
        with admin.connect() as connection:
            connection.execute(text(f"CREATE DATABASE {name}"))
        try:
            yield (
                engine,
                dict(
                    os.environ, DATABASE_URL=url.render_as_string(hide_password=False)
                ),
            )
        finally:
            engine.dispose()
            with admin.connect() as connection:
                connection.execute(text(f"DROP DATABASE {name}"))
    finally:
        admin.dispose()


def test_classification_downgrade_is_lossless_or_blocked(disposable_postgres):
    engine, env = disposable_postgres

    def alembic(*args):
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
        )

    def check_alembic(*args):
        result = alembic(*args)
        assert result.returncode == 0, result.stderr

    check_alembic("upgrade", PREVIOUS)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO sales (customer_email, amount, currency, payment_status) "
                "VALUES ('one@example.test', 50, 'RUB', 'paid'), "
                "('two@example.test', 50, 'RUB', 'paid'), "
                "('three@example.test', 50, 'RUB', 'paid')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO purchase_email_deliveries (sale_id, status, attempt_count) "
                "SELECT id, 'pending', 0 FROM sales ORDER BY id"
            )
        )

    check_alembic("upgrade", "head")
    check_alembic("downgrade", PREVIOUS)
    assert "failure_classification" not in {
        column["name"]
        for column in inspect(engine).get_columns("purchase_email_deliveries")
    }
    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == PREVIOUS
        )
        assert (
            connection.scalar(text("SELECT count(*) FROM purchase_email_deliveries"))
            == 3
        )
    check_alembic("upgrade", "head")
    check_alembic("check")

    classifications = ["transient", "permanent", "unknown"]
    with engine.begin() as connection:
        ids = connection.scalars(
            text("SELECT id FROM purchase_email_deliveries ORDER BY id")
        ).all()
        assert len(ids) == len(classifications)
        for delivery_id, classification in zip(ids, classifications, strict=True):
            connection.execute(
                text(
                    "UPDATE purchase_email_deliveries SET status = 'failed', "
                    "failure_classification = :classification WHERE id = :id"
                ),
                {"id": delivery_id, "classification": classification},
            )

    blocked = alembic("downgrade", PREVIOUS)
    assert blocked.returncode != 0
    assert (
        "Downgrade blocked: purchase email failure classifications would be lost."
        in blocked.stderr
    )
    assert "archive and explicitly migrate the classifications" in blocked.stderr
    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == REVISION
        )
        rows = connection.execute(
            text(
                "SELECT id, status, failure_classification "
                "FROM purchase_email_deliveries ORDER BY id"
            )
        ).all()
        assert rows == list(zip(ids, ["failed"] * 3, classifications, strict=True))
    check_alembic("check")
