import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from urllib.parse import quote

from app.core.sale_reference import SALE_REFERENCE_PATTERN
from app.models.enums import SaleItemType
from app.models.sale import Sale

TEMPLATE_DIRECTORY = (
    Path(__file__).resolve().parents[1] / "templates" / "purchase_email"
)
LINK_MARKER = re.compile(r"\[\[(download|booking):([^\[\]{}\n]+)\]\]")
PRODUCT_PLACEHOLDER = "{{ product_name }}"
REFERENCE_PLACEHOLDER = "{{ sale_reference }}"
COPY_PLACEHOLDER = re.compile(
    f"{re.escape(PRODUCT_PLACEHOLDER)}|{re.escape(REFERENCE_PLACEHOLDER)}"
)
TEMPLATE_DELIMITERS = ("[[", "]]", "{{", "}}")


class PurchaseEmailRenderError(Exception):
    """Raised when fulfilled purchase access cannot be rendered safely."""


class PurchaseEmailExpiredDownloadError(PurchaseEmailRenderError):
    """Raised when an email would contain an already expired download link."""


@dataclass(frozen=True)
class RenderedPurchaseEmail:
    subject: str
    text_body: str
    html_body: str


def _validate_template(
    subject: str, source: str, links: dict[str, str], product_name: str
) -> None:
    markers = list(LINK_MARKER.finditer(source))
    if sorted(marker[1] for marker in markers) != sorted(links) or any(
        not marker[2].strip() for marker in markers
    ):
        raise PurchaseEmailRenderError(
            "Purchase email template has invalid access markers."
        )

    expected_product_names = int("download" in links)
    if source.count(PRODUCT_PLACEHOLDER) != expected_product_names:
        raise PurchaseEmailRenderError(
            "Purchase email template has an invalid product name placeholder count."
        )

    remaining = LINK_MARKER.sub("", source)
    if remaining.count(REFERENCE_PLACEHOLDER) != 1:
        raise PurchaseEmailRenderError(
            "Purchase email template has an invalid purchase reference placeholder count."
        )
    remaining = remaining.replace(REFERENCE_PLACEHOLDER, "")
    if "download" in links and product_name.strip():
        remaining = remaining.replace(PRODUCT_PLACEHOLDER, "")
    if any(
        delimiter in subject or delimiter in remaining
        for delimiter in TEMPLATE_DELIMITERS
    ):
        raise PurchaseEmailRenderError("Purchase email template has unresolved markup.")


def _render_bodies(
    source: str, links: dict[str, str], product_name: str, sale_reference: str
) -> tuple[str, str]:
    text_parts: list[str] = []
    html_parts: list[str] = []
    values = {PRODUCT_PLACEHOLDER: product_name, REFERENCE_PLACEHOLDER: sale_reference}

    def append_copy(copy: str) -> None:
        text_parts.append(
            COPY_PLACEHOLDER.sub(lambda match: values[match[0]], copy.replace("**", ""))
        )
        formatted = re.sub(r"\*\*([^\n]+?)\*\*", r"<strong>\1</strong>", escape(copy))
        html_parts.append(
            COPY_PLACEHOLDER.sub(lambda match: escape(values[match[0]]), formatted)
        )

    start = 0
    for marker in LINK_MARKER.finditer(source):
        append_copy(source[start : marker.start()])
        text_parts.append(links[marker[1]])
        url = escape(links[marker[1]], quote=True)
        label = escape(marker[2])
        html_parts.append(
            '<a style="display:inline-block;padding:10px 16px;background:#1d4ed8;'
            'color:#fff;border-radius:6px;text-decoration:none" '
            f'href="{url}">{label}</a>'
        )
        start = marker.end()
    append_copy(source[start:])
    html_body = "".join(
        "<p>" + paragraph.replace("\n", "<br>") + "</p>"
        for paragraph in "".join(html_parts).split("\n\n")
    )
    return "".join(text_parts), html_body


def render_purchase_email(
    sale: Sale,
    *,
    public_base_url: str,
    now: datetime,
) -> RenderedPurchaseEmail:
    base_url = public_base_url.rstrip("/")
    if not base_url:
        raise PurchaseEmailRenderError("Public application URL is not configured.")
    if not sale.sale_reference or not SALE_REFERENCE_PATTERN.fullmatch(sale.sale_reference):
        raise PurchaseEmailRenderError("Purchase has an invalid purchase reference.")

    links = {}
    product_name = ""
    for item in sale.items:
        if item.item_type == SaleItemType.PRODUCT:
            entitlement = item.download_entitlement
            if entitlement is None or "download" in links:
                raise PurchaseEmailRenderError("Invalid product purchase access.")
            expires_at = entitlement.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= now:
                raise PurchaseEmailExpiredDownloadError()
            product_name = item.item_name
            token = quote(entitlement.download_token, safe="")
            links["download"] = f"{base_url}/download/{token}"
        elif item.item_type == SaleItemType.SERVICE:
            entitlement = item.consultation_entitlement
            if entitlement is None or "booking" in links:
                raise PurchaseEmailRenderError("Invalid consultation purchase access.")
            token = quote(entitlement.booking_token, safe="")
            links["booking"] = f"{base_url}/consultation/book/{token}"
        else:
            raise PurchaseEmailRenderError("Purchase contains an unsupported item.")

    if not links:
        raise PurchaseEmailRenderError("Purchase has no fulfilled items.")

    if len(links) == 2:
        composition = "bundle"
    else:
        composition = "product" if "download" in links else "consultation"
    language = "ru" if sale.purchase_language == "ru" else "en"
    template = TEMPLATE_DIRECTORY / f"{composition}_{language}.txt"
    try:
        subject, source = template.read_text(encoding="utf-8").strip().split("\n\n", 1)
    except (OSError, ValueError) as exc:
        raise PurchaseEmailRenderError(
            "Purchase email template is unavailable."
        ) from exc
    source = source.replace("\\\n", "\n")
    _validate_template(subject, source, links, product_name)

    text_body, html_body = _render_bodies(source, links, product_name, sale.sale_reference)
    return RenderedPurchaseEmail(subject, text_body, html_body)
