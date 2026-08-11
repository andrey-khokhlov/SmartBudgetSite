from dataclasses import dataclass
from html import escape
from urllib.parse import quote

from app.models.enums import SaleItemType
from app.models.sale import Sale


class PurchaseEmailRenderError(Exception):
    """Raised when fulfilled purchase access cannot be rendered safely."""


@dataclass(frozen=True)
class RenderedPurchaseEmail:
    subject: str
    text_body: str
    html_body: str


def render_purchase_email(
    sale: Sale,
    *,
    public_base_url: str,
    support_email: str,
) -> RenderedPurchaseEmail:
    base_url = public_base_url.rstrip("/")
    if not base_url:
        raise PurchaseEmailRenderError("Public application URL is not configured.")

    access_entries: list[tuple[str, str]] = []
    for item in sorted(sale.items, key=lambda candidate: candidate.id):
        if item.item_type == SaleItemType.PRODUCT:
            entitlement = item.download_entitlement
            if entitlement is None:
                raise PurchaseEmailRenderError(
                    "Product purchase has no download entitlement."
                )
            path = f"/download/{quote(entitlement.download_token, safe='')}"
        elif item.item_type == SaleItemType.SERVICE:
            entitlement = item.consultation_entitlement
            if entitlement is None:
                raise PurchaseEmailRenderError(
                    "Consultation purchase has no booking entitlement."
                )
            path = f"/consultation/book/{quote(entitlement.booking_token, safe='')}"
        else:
            raise PurchaseEmailRenderError("Purchase contains an unsupported item.")
        access_entries.append((item.item_name, f"{base_url}{path}"))

    if not access_entries:
        raise PurchaseEmailRenderError("Purchase has no fulfilled items.")

    text_lines = [
        "Payment confirmed — thank you for your purchase.",
        "",
        "Your access:",
    ]
    html_items: list[str] = []
    for item_name, access_url in access_entries:
        text_lines.extend([f"- {item_name}", f"  {access_url}"])
        html_items.append(
            f"<li><strong>{escape(item_name)}</strong><br>"
            f'<a href="{escape(access_url, quote=True)}">Open protected access</a></li>'
        )

    text_lines.extend(["", f"Support: {support_email}"])
    html_body = (
        "<p>Payment confirmed — thank you for your purchase.</p>"
        "<p>Your access:</p>"
        f"<ul>{''.join(html_items)}</ul>"
        f"<p>Support: {escape(support_email)}</p>"
    )
    return RenderedPurchaseEmail(
        subject="Your SmartBudget purchase access",
        text_body="\n".join(text_lines),
        html_body=html_body,
    )
