from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.enums import SaleItemType
from app.models.purchase_delivery_incident import PurchaseDeliveryIncident
from app.models.purchase_email_delivery import PurchaseEmailDeliveryStatus
from app.repositories.purchase_delivery_monitoring_repository import (
    get_incident_for_update,
    lock_incident_writes,
    read_open_incidents,
    read_open_operator_incidents,
    read_paid_fulfillment,
)
from app.repositories.resend_webhook_repository import (
    add_operator_incident,
    delete_expired_receipts,
    read_overdue_receipts,
)
from app.services.consultation_entitlement_service import CONSULTATION_SERVICE_TYPE
from app.services.webhooks.resend_webhook_service import (
    CONFIRMATION_TIMEOUT,
    RECEIPT_RETENTION,
)

EMAIL_STALL_THRESHOLD = timedelta(minutes=5)
EMAIL_ERRORS = {
    PurchaseEmailDeliveryStatus.FAILED: "email_failed",
    PurchaseEmailDeliveryStatus.RECONCILIATION_REQUIRED: "email_reconciliation_required",
}
EMAIL_WARNINGS = {
    PurchaseEmailDeliveryStatus.PENDING: "email_pending_stalled",
    PurchaseEmailDeliveryStatus.SENDING: "email_sending_stalled",
}


def _email_finding(row, now: datetime) -> tuple[str, str] | None:
    status = row.email_status
    if status is None:
        return "email_record_missing", "error"
    if status in EMAIL_ERRORS:
        return EMAIL_ERRORS[status], "error"
    if status in EMAIL_WARNINGS:
        started_at = row.email_created_at
        if (
            status == PurchaseEmailDeliveryStatus.SENDING
            and row.sending_started_at is not None
        ):
            started_at = row.sending_started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        if now - started_at >= EMAIL_STALL_THRESHOLD:
            return EMAIL_WARNINGS[status], "warning"
    return None


def _item_fulfilled(row) -> bool:
    if row.item_type == SaleItemType.PRODUCT:
        return (
            row.download_release_id is not None
            and row.download_release_id == row.product_release_id
            and row.consultation_id is None
        )
    return (
        row.item_type == SaleItemType.SERVICE
        and row.service_type == CONSULTATION_SERVICE_TYPE
        and row.consultation_id is not None
        and row.download_release_id is None
    )


def scan_purchase_delivery(db: Session, *, now: datetime | None = None) -> dict:
    """Run one atomic monitoring pass using a fresh session."""
    findings: dict[tuple[int, int, str], str] = {}
    provider_origins: dict[tuple[int, int, str], str] = {}
    paid_sales = 0
    previous_sale_id = None
    with db.begin():
        lock_incident_writes(db)
        observed_at = now or datetime.now(UTC)
        for row in read_paid_fulfillment(db):
            if row.sale_id != previous_sale_id:
                paid_sales += 1
                previous_sale_id = row.sale_id
                email_finding = _email_finding(row, observed_at)
                if email_finding:
                    kind, severity = email_finding
                    findings[row.sale_id, row.sale_id, kind] = severity
                if row.provider_delivery_status == "delivery_delayed":
                    key = (row.sale_id, row.email_delivery_id, "email_provider_delayed")
                    findings[key] = "warning"
                    if row.provider_event_id is not None:
                        provider_origins[key] = row.provider_event_id

            if row.item_id is None:
                findings[row.sale_id, row.sale_id, "sale_items_missing"] = "error"
            elif not _item_fulfilled(row):
                findings[row.sale_id, row.item_id, "item_fulfillment_invalid"] = "error"

        open_incidents = {
            (incident.sale_id, incident.subject_id, incident.kind): incident
            for incident in read_open_incidents(db)
        }
        opened = 0
        for key, severity in findings.items():
            incident = open_incidents.pop(key, None)
            if incident is None:
                sale_id, subject_id, kind = key
                db.add(
                    PurchaseDeliveryIncident(
                        sale_id=sale_id,
                        subject_id=subject_id,
                        kind=kind,
                        severity=severity,
                        originating_event_id=provider_origins.get(key),
                        first_detected_at=observed_at,
                        last_observed_at=observed_at,
                    )
                )
                opened += 1
            else:
                incident.severity = severity
                incident.last_observed_at = observed_at

        for incident in open_incidents.values():
            incident.resolved_at = observed_at

        expired_before = observed_at - RECEIPT_RETENTION
        for receipt, sale_id in read_overdue_receipts(
            db, cutoff=observed_at - CONFIRMATION_TIMEOUT, expires_before=expired_before
        ):
            opened += add_operator_incident(
                db,
                sale_id=sale_id,
                delivery_id=receipt.delivery_id,
                kind="email_provider_confirmation_overdue",
                event_id=receipt.svix_id,
                now=observed_at,
            )
        operator_incidents = read_open_operator_incidents(db)

    # Receipt cleanup never waits on receipt rows while holding the incident lock.
    with db.begin():
        delete_expired_receipts(db, expired_before)

    return {
        "paid_sales_scanned": paid_sales,
        "open_incidents": len(findings) + len(operator_incidents),
        "opened": opened,
        "resolved": len(open_incidents),
        "by_kind": dict(
            Counter(kind for _, _, kind in findings)
            + Counter(kind for kind, _ in operator_incidents)
        ),
        "by_severity": dict(
            Counter(findings.values())
            + Counter(severity for _, severity in operator_incidents)
        ),
    }


def resolve_operator_incident(
    db: Session, *, incident_id: int, operator: str, reason: str, confirmed: bool
) -> bool:
    operator = operator.strip()
    reason = reason.strip()
    if not confirmed or not 0 < len(operator) <= 128 or not 0 < len(reason) <= 1000:
        raise ValueError("Confirmation, operator and resolution reason are required.")
    with db.begin():
        incident = get_incident_for_update(db, incident_id)
        if (
            incident is None
            or not incident.requires_operator
            or incident.resolved_at is not None
        ):
            return False
        incident.resolved_at = datetime.now(UTC)
        incident.resolved_by = operator
        incident.resolution_reason = reason
    return True
