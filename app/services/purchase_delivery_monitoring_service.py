from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.enums import SaleItemType
from app.models.purchase_delivery_incident import PurchaseDeliveryIncident
from app.models.purchase_email_delivery import PurchaseEmailDeliveryStatus
from app.repositories.purchase_delivery_monitoring_repository import (
    lock_incident_writes,
    read_open_incidents,
    read_paid_fulfillment,
)
from app.services.consultation_entitlement_service import CONSULTATION_SERVICE_TYPE

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

    return {
        "paid_sales_scanned": paid_sales,
        "open_incidents": len(findings),
        "opened": opened,
        "resolved": len(open_incidents),
        "by_kind": dict(Counter(kind for _, _, kind in findings)),
        "by_severity": dict(Counter(findings.values())),
    }
