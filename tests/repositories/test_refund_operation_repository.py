from unittest.mock import Mock

from sqlalchemy.dialects import postgresql

from app.repositories.refund_operation_repository import RefundOperationRepository


def compiled_sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    ).upper()


def test_refund_repository_locks_sale_and_operation_rows():
    db = Mock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    repository = RefundOperationRepository(db)

    repository.lock_sale(12)
    sale_sql = compiled_sql(db.execute.call_args.args[0])
    repository.lock_by_sale_id(12)
    refund_sql = compiled_sql(db.execute.call_args.args[0])

    assert "FROM SALES" in sale_sql
    assert sale_sql.endswith("FOR UPDATE")
    assert "FROM REFUND_OPERATIONS" in refund_sql
    assert refund_sql.endswith("FOR UPDATE")


def test_refund_repository_locks_both_entitlement_sets():
    db = Mock()
    db.execute.return_value.scalars.return_value = []
    repository = RefundOperationRepository(db)

    repository.lock_download_entitlements(12)
    download_sql = compiled_sql(db.execute.call_args.args[0])
    repository.lock_consultation_entitlements(12)
    consultation_sql = compiled_sql(db.execute.call_args.args[0])

    assert "FROM DOWNLOAD_ENTITLEMENTS" in download_sql
    assert download_sql.endswith("FOR UPDATE")
    assert "FROM CONSULTATION_ENTITLEMENTS" in consultation_sql
    assert consultation_sql.endswith("FOR UPDATE")
