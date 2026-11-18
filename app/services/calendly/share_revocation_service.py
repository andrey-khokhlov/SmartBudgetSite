from collections import Counter
from datetime import UTC, datetime, timedelta
from time import monotonic

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.consultation_entitlement import ConsultationEntitlement as Entitlement
from app.models.consultation_entitlement import ConsultationEntitlementStatus
from app.repositories.consultation_entitlement_repository import (
    ConsultationEntitlementRepository as Repository,
)
from app.repositories.lava_top_payment_recovery_repository import lock_recovery_pass
from app.services.calendly.calendly_api_client import (
    CalendlyAPIError,
    delete_share,
    resource_path,
)
from app.services.calendly.share_service import recover_share, share_details
from app.services.consultation_entitlement_service import _ensure_utc_aware

REVOCATION_LOCK_ID = 812194340107
BATCH_SIZE = 20
PASS_START_BUDGET_SECONDS = 40


def _lock_entitlement(db: Session, entitlement_id: int) -> Entitlement | None:
    return Repository.lock_owner_and_entitlement(db, Entitlement.id, entitlement_id)


def _eligible(entitlement: Entitlement | None, now: datetime) -> bool:
    return (
        entitlement is not None
        and _ensure_utc_aware(entitlement.expires_at) <= now
        and entitlement.status != ConsultationEntitlementStatus.BOOKED
        and entitlement.booked_at is None
        and entitlement.provider_event_uri is None
        and entitlement.provider_invitee_uri is None
        and entitlement.calendly_revoked_at is None
        and entitlement.calendly_revoke_outcome != "provider_booked"
    )


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(3600, 60 * 2 ** min(attempts - 1, 6)))


def _lookup_claim(event_type, reference, claimed_at) -> tuple[dict, str]:
    if not (event_type and reference and claimed_at):
        raise CalendlyAPIError(
            "Calendly Share ownership is unresolved.", outcome="ownership_unresolved"
        )
    resource_path(event_type, "event_types")
    marker = f"SmartBudgetSite:{reference}"
    return recover_share(event_type, marker, _ensure_utc_aware(claimed_at)), marker


def _revoke_one(db: Session, entitlement_id: int, now: datetime) -> str:
    with db.begin():
        entitlement = _lock_entitlement(db, entitlement_id)
        if not _eligible(entitlement, now):
            return "skipped"
        if (
            entitlement.calendly_revoke_next_at
            and _ensure_utc_aware(entitlement.calendly_revoke_next_at) > now
        ):
            return "skipped"
        attempts = entitlement.calendly_revoke_attempts + 1
        entitlement.calendly_revoke_attempts = attempts
        entitlement.calendly_revoke_next_at = now + _backoff(attempts)
        entitlement.calendly_revoke_outcome = "attempt_started"
        share_uri = entitlement.calendly_share_uri
        event_type = entitlement.calendly_event_type_uri
        reference = entitlement.provisioning_reference
        claimed_at = entitlement.provisioning_claimed_at

    outcome = "revoked"
    retry_at = None
    try:
        if not share_uri:
            resource, marker = _lookup_claim(event_type, reference, claimed_at)
            if resource.get("status") in ("booked", "expired"):
                recovered_uri = resource.get("uri")
                resource_path(recovered_uri, "shares")
                url = None
                if resource["status"] == "booked":
                    outcome = "provider_booked"
            else:
                recovered_uri, url = share_details(resource, event_type, marker)
            with db.begin():
                entitlement = _lock_entitlement(db, entitlement_id)
                if not _eligible(entitlement, now):
                    return "skipped"
                if entitlement.calendly_share_uri not in (None, recovered_uri):
                    raise CalendlyAPIError(
                        "Calendly Share ownership is unresolved.",
                        outcome="ownership_unresolved",
                    )
                if not entitlement.calendly_share_uri:
                    entitlement.calendly_share_uri = recovered_uri
                    entitlement.calendly_booking_url = url
                share_uri = recovered_uri

        if outcome != "provider_booked":
            try:
                delete_share(share_uri)
            except CalendlyAPIError as error:
                if error.outcome != "provider_conflict":
                    raise
                try:
                    resource, _ = _lookup_claim(event_type, reference, claimed_at)
                except CalendlyAPIError as lookup_error:
                    if lookup_error.outcome != "ownership_unresolved":
                        raise
                else:
                    if (
                        resource.get("uri") == share_uri
                        and resource.get("status") == "booked"
                    ):
                        outcome = "provider_booked"
                    else:
                        raise error
                if outcome != "provider_booked":
                    raise error
    except CalendlyAPIError as error:
        outcome, retry_at = error.outcome, error.retry_at
    except ValueError:
        outcome = "ownership_unresolved"

    finished_at = max(now, datetime.now(UTC))
    with db.begin():
        entitlement = _lock_entitlement(db, entitlement_id)
        if entitlement is None:
            return "skipped"
        entitlement.calendly_revoke_outcome = outcome
        if outcome == "revoked":
            entitlement.calendly_revoked_at = finished_at
        entitlement.calendly_revoke_next_at = (
            None
            if outcome in ("revoked", "provider_booked")
            else max(finished_at + _backoff(attempts), retry_at or finished_at)
        )
    return outcome


def revoke_expired_shares(
    db: Session,
    *,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(UTC)
    with lock_recovery_pass(db.get_bind(), lock_id=REVOCATION_LOCK_ID) as acquired:
        if not acquired:
            return {"status": "already_running"}
        with db.begin():
            due = Repository.due_share_revocations(db, now, BATCH_SIZE)
            cooldown = db.scalar(
                select(func.max(Entitlement.calendly_revoke_next_at)).where(
                    Entitlement.calendly_revoke_outcome == "rate_limited",
                    Entitlement.calendly_revoke_next_at > now,
                )
            )
        if dry_run:
            return {"status": "dry_run", "selected": len(due)}
        if cooldown is not None:
            return {
                "status": "rate_limited",
                "retry_at": _ensure_utc_aware(cooldown).isoformat(),
            }
        start = monotonic()
        outcomes: Counter[str] = Counter()
        unresolved = []
        for entitlement_id in due:
            if monotonic() - start >= PASS_START_BUDGET_SECONDS:
                break
            outcome = _revoke_one(db, entitlement_id, now)
            outcomes[outcome] += 1
            if outcome not in ("revoked", "skipped"):
                unresolved.append(entitlement_id)
            if outcome in ("rate_limited", "unauthorized", "forbidden"):
                break
        return {
            "status": "completed",
            "selected": len(due),
            "by_outcome": dict(outcomes),
            "unresolved_entitlements": unresolved,
        }
