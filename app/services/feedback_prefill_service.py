from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.i18n import t
from app.repositories.download_entitlement_repository import (
    DownloadEntitlementRepository,
)
from app.services.support_reference_service import (
    is_valid_download_support_reference,
)


@dataclass(frozen=True)
class DownloadFeedbackPrefillContext:
    """Safe customer-facing context for a download support message."""

    message_type: str
    customer_email: str
    support_reference: str
    product_name: str
    product_edition: str | None
    release_version: str
    purchase_date: str | None
    subject: str
    message: str


def _product_label(product_name: str, product_edition: str | None) -> str:
    if product_edition:
        return f"{product_name} ({product_edition})"
    return product_name


def _format_purchase_date(value: datetime | None, lang: str) -> str | None:
    if value is None:
        return None
    if lang == "ru":
        return value.strftime("%d.%m.%Y")
    return value.strftime("%Y-%m-%d")


def get_download_feedback_prefill_context(
    db: Session,
    support_reference: str,
    lang: str,
) -> DownloadFeedbackPrefillContext | None:
    """Resolve safe prefill data from an existing public download reference."""
    if not is_valid_download_support_reference(support_reference):
        return None

    entitlement = DownloadEntitlementRepository(db).get_by_support_reference(
        support_reference
    )
    if entitlement is None:
        return None

    sale_item = entitlement.sale_item
    release = entitlement.release
    sale = sale_item.sale if sale_item is not None else None
    if sale_item is None or release is None or sale is None:
        return None

    product = sale_item.product or release.product
    product_name = product.name if product is not None else sale_item.item_name
    product_edition = product.edition if product is not None else None
    purchase_date = _format_purchase_date(sale.created_at, lang)
    product_label = _product_label(product_name, product_edition)

    message_lines = [
        t(lang, "feedback_download_prefill_message_intro").format(
            product=product_label
        ),
        "",
        t(lang, "feedback_download_prefill_version").format(version=release.version),
    ]
    if purchase_date is not None:
        message_lines.append(
            t(lang, "feedback_download_prefill_purchase_date").format(
                purchase_date=purchase_date
            )
        )
    message_lines.extend(
        [
            t(lang, "feedback_download_prefill_reference").format(
                support_reference=support_reference
            ),
            "",
            t(lang, "feedback_download_prefill_details_prompt"),
        ]
    )

    subject = t(lang, "feedback_download_prefill_subject").format(
        product=product_label
    )[:200]

    return DownloadFeedbackPrefillContext(
        message_type="purchase_or_download_issue",
        customer_email=sale.customer_email,
        support_reference=support_reference,
        product_name=product_name,
        product_edition=product_edition,
        release_version=release.version,
        purchase_date=purchase_date,
        subject=subject,
        message="\n".join(message_lines)[:2000],
    )
