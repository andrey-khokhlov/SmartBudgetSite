import re
from datetime import UTC, date, datetime
from html import escape
from pathlib import Path

import pytest

from app.core.config import settings
from app.services import purchase_email_renderer as renderer
from app.services.payment_reconciliation_service import reconcile_payment_event
from tests.services.test_purchase_email_delivery_service import (
    create_pending_sale,
    payment_event,
)

POLICY_MARKER = "[[refund_policy:Policy]]"
POLICY_PATH = "/legal/refund-policy"


@pytest.mark.parametrize(
    "section,kind", [(1, "consultation"), (2, "product"), (3, "bundle")]
)
@pytest.mark.parametrize("language", ["ru", "en"])
def test_purchase_template_matches_approved_copy(section, kind, language):
    requirements = (
        Path(__file__).resolve().parents[2] / "docs" / "release_uiux_requirements.md"
    ).read_text(encoding="utf-8")
    copy = requirements.split(f"#### 5.8.{section}.", 1)[1].split(
        f"#### 5.8.{section + 1}.", 1
    )[0]
    approved = (
        copy.split(f"##### {language.upper()}\n\n", 1)[1]
        .split("\n##### ", 1)[0]
        .strip()
    )
    template = (
        (renderer.TEMPLATE_DIRECTORY / f"{kind}_{language}.txt")
        .read_text(encoding="utf-8")
        .strip()
    )
    documented = renderer.LINK_MARKER.sub(
        lambda marker: (
            f"{marker[2]} (`{POLICY_PATH}`)"
            if marker[1] == "refund_policy"
            else f"[{marker[2]}]"
        ),
        template,
    )
    assert "**Subject:** " + documented == approved


@pytest.mark.parametrize("kind", ["product", "consultation", "bundle"])
@pytest.mark.parametrize("language", ["ru", "en"])
@pytest.mark.parametrize("published", [True, False])
def test_renderer_links_policy_only_for_published_separate_purchase(
    db_session, monkeypatch, kind, language, published
):
    monkeypatch.setattr(
        settings, "REFUND_POLICY_PUBLICATION_DATE", date(2000, 1, 2) if published else None
    )
    monkeypatch.setattr(settings, "SELLER_ADDRESS_RU", "Учебный адрес")
    monkeypatch.setattr(settings, "SELLER_ADDRESS_EN", "Fictional Seller Address")
    monkeypatch.setattr(settings, "SELLER_CONTACT_PHONE", "+1 202-555-0147")
    sale = create_pending_sale(db_session, kind=kind, language=language)
    reconcile_payment_event(db_session, payment_event(sale))
    db_session.commit()

    rendered = renderer.render_purchase_email(
        sale, public_base_url="https://app.example.test/", now=datetime.now(UTC)
    )
    policy_url = f"https://app.example.test{POLICY_PATH}"
    title = (
        "Политике отмены и возвратов" if language == "ru" else "Cancellation and Refund Policy"
    )
    for body in (rendered.text_body, rendered.html_body):
        assert sale.sale_reference in body
        assert ("https://app.example.test/download/" in body) == (kind != "consultation")
        assert ("https://app.example.test/consultation/book/" in body) == (kind != "product")
        assert "[[" not in body and "{{" not in body
    if kind == "bundle":
        assert title not in rendered.text_body
        assert title not in rendered.html_body
        assert policy_url not in rendered.text_body
        assert policy_url not in rendered.html_body
        return

    source = (renderer.TEMPLATE_DIRECTORY / f"{kind}_{language}.txt").read_text(
        encoding="utf-8"
    )
    paragraph = next(line for line in source.splitlines() if "[[refund_policy:" in line)
    approved = paragraph.replace(f"[[refund_policy:{title}]]", title)
    text = approved.replace(title, f"{title} ({policy_url})") if published else approved
    html = escape(approved)
    if published:
        html = html.replace(title, f'<a href="{policy_url}">{title}</a>')
    else:
        assert policy_url not in rendered.text_body
        assert policy_url not in rendered.html_body
    assert f"\n\n{text}\n\n" in rendered.text_body
    assert f"<p>{html}</p>" in rendered.html_body


@pytest.mark.parametrize(
    ("public_base_url", "seller_phone", "has_link"),
    [
        ("https://app.example.test", "+1 202-555-0147", True),
        ("http://app.example.test", "+1 202-555-0147", False),
        ("https://app.example.test", "", False),
    ],
)
def test_policy_link_requires_https_and_complete_publication_settings(
    db_session, tmp_path, monkeypatch, public_base_url, seller_phone, has_link
):
    monkeypatch.setattr(settings, "REFUND_POLICY_PUBLICATION_DATE", date(2000, 1, 2))
    monkeypatch.setattr(settings, "SELLER_ADDRESS_RU", "Учебный адрес")
    monkeypatch.setattr(settings, "SELLER_ADDRESS_EN", "Fictional Seller Address")
    monkeypatch.setattr(settings, "SELLER_CONTACT_PHONE", seller_phone)
    sale = create_pending_sale(db_session, kind="consultation")
    reconcile_payment_event(db_session, payment_event(sale))
    db_session.commit()
    monkeypatch.setattr(renderer, "TEMPLATE_DIRECTORY", tmp_path)
    label = '<Policy & "terms">'
    (tmp_path / "consultation_en.txt").write_text(
        f"Subject\n\n[[booking:Book]]\n\n[[refund_policy:{label}]]\n\n{{{{ sale_reference }}}}",
        encoding="utf-8",
    )

    rendered = renderer.render_purchase_email(
        sale, public_base_url=public_base_url, now=datetime.now(UTC)
    )
    policy_url = f"{public_base_url}{POLICY_PATH}"
    escaped = escape(label)
    assert label in rendered.text_body
    assert label not in rendered.html_body
    assert escaped in rendered.html_body
    if has_link:
        assert f"{label} ({policy_url})" in rendered.text_body
        assert f'<a href="{policy_url}">{escaped}</a>' in rendered.html_body
    else:
        assert policy_url not in rendered.text_body
        assert policy_url not in rendered.html_body


@pytest.mark.parametrize(
    "kind,body",
    [
        ("product", "No download marker"),
        ("product", "[[download:one]] [[download:two]]"),
        ("product", "[[download:one]] [[booking:unexpected]]"),
        ("consultation", "[[download:wrong kind]]"),
        ("consultation", "[[booking:   ]]"),
        ("consultation", "[[booking:valid]] [[video:unsupported]]"),
        ("consultation", "[[booking:valid]] [[malformed"),
        ("consultation", "[[booking:valid]] {{ product_name }}"),
        ("consultation", "[[booking:{{ product_name }}]]"),
        ("bundle", "[[download:valid]]"),
        ("bundle", "[[download:valid]] [[booking:valid]] {{ unknown }}"),
        ("bundle", "[[download:valid]] [[booking:valid]] {{product_name}}"),
        ("bundle", "[[download:valid]] [[booking:valid]] [[refund_policy:Unexpected]]"),
    ],
)
def test_renderer_rejects_invalid_template(
    db_session, tmp_path, monkeypatch, kind, body
):
    sale = create_pending_sale(db_session, kind=kind)
    reconcile_payment_event(db_session, payment_event(sale))
    db_session.commit()
    monkeypatch.setattr(renderer, "TEMPLATE_DIRECTORY", tmp_path)
    if kind != "bundle":
        body = f"{body}\n\n{POLICY_MARKER}"
    (tmp_path / f"{kind}_en.txt").write_text(
        f"Subject\n\n{body}\n\n{{{{ sale_reference }}}}", encoding="utf-8"
    )

    with pytest.raises(renderer.PurchaseEmailRenderError, match="template"):
        renderer.render_purchase_email(
            sale, public_base_url="https://app.example.test", now=datetime.now(UTC)
        )


@pytest.mark.parametrize(
    "policy",
    ["", "[[refund_policy:   ]]", "[[refund_policy:bad label", POLICY_MARKER * 2],
)
def test_renderer_rejects_missing_or_invalid_policy_marker(
    db_session, tmp_path, monkeypatch, policy
):
    sale = create_pending_sale(db_session, kind="consultation")
    reconcile_payment_event(db_session, payment_event(sale))
    db_session.commit()
    monkeypatch.setattr(renderer, "TEMPLATE_DIRECTORY", tmp_path)
    (tmp_path / "consultation_en.txt").write_text(
        f"Subject\n\n[[booking:Book]]\n\n{policy}\n\n{{{{ sale_reference }}}}",
        encoding="utf-8",
    )
    with pytest.raises(renderer.PurchaseEmailRenderError, match="invalid link markers"):
        renderer.render_purchase_email(
            sale, public_base_url="https://app.example.test", now=datetime.now(UTC)
        )


@pytest.mark.parametrize("kind", ["product", "bundle"])
@pytest.mark.parametrize("count", [0, 2], ids=["missing", "duplicate"])
def test_renderer_rejects_wrong_product_name_count(
    db_session, tmp_path, monkeypatch, kind, count
):
    sale = create_pending_sale(db_session, kind=kind)
    reconcile_payment_event(db_session, payment_event(sale))
    db_session.commit()
    markers = ["[[download:Download]]"]
    if kind == "bundle":
        markers.append("[[booking:Book]]")
    else:
        markers.append(POLICY_MARKER)
    body = "\n\n".join(markers + ["{{ product_name }}"] * count + ["{{ sale_reference }}"])
    monkeypatch.setattr(renderer, "TEMPLATE_DIRECTORY", tmp_path)
    (tmp_path / f"{kind}_en.txt").write_text(f"Subject\n\n{body}", encoding="utf-8")

    with pytest.raises(
        renderer.PurchaseEmailRenderError, match="invalid product name placeholder count"
    ):
        renderer.render_purchase_email(
            sale, public_base_url="https://app.example.test", now=datetime.now(UTC)
        )


def test_renderer_escapes_link_label_in_html(db_session, tmp_path, monkeypatch):
    sale = create_pending_sale(db_session, kind="consultation")
    reconcile_payment_event(db_session, payment_event(sale))
    db_session.commit()
    monkeypatch.setattr(renderer, "TEMPLATE_DIRECTORY", tmp_path)
    (tmp_path / "consultation_en.txt").write_text(
        'Subject\n\n[[booking:**<script> & "book"**]]\n\n'
        f"{POLICY_MARKER}\n\n"
        "{{ sale_reference }}",
        encoding="utf-8",
    )

    rendered = renderer.render_purchase_email(
        sale, public_base_url="https://app.example.test", now=datetime.now(UTC)
    )

    assert re.fullmatch(
        r"https://app\.example\.test/consultation/book/[\w-]+",
        rendered.text_body.split("\n\n")[0],
    )
    assert "**&lt;script&gt; &amp; &quot;book&quot;**</a>" in rendered.html_body
    assert "<script>" not in rendered.html_body


@pytest.mark.parametrize("placeholder", ["", "{{ sale_reference }} {{ sale_reference }}"])
def test_renderer_rejects_invalid_reference_placeholder(
    db_session, tmp_path, monkeypatch, placeholder
):
    sale = create_pending_sale(db_session, kind="consultation")
    reconcile_payment_event(db_session, payment_event(sale))
    monkeypatch.setattr(renderer, "TEMPLATE_DIRECTORY", tmp_path)
    (tmp_path / "consultation_en.txt").write_text(
        f"Subject\n\n[[booking:Book]]\n\n{POLICY_MARKER}\n\n{placeholder}",
        encoding="utf-8",
    )
    with pytest.raises(renderer.PurchaseEmailRenderError, match="reference placeholder"):
        renderer.render_purchase_email(
            sale, public_base_url="https://app.example.test", now=datetime.now(UTC)
        )


@pytest.mark.parametrize("reference", [None, "PAY-<script>"])
def test_renderer_rejects_invalid_reference_value(db_session, reference):
    sale = create_pending_sale(db_session, kind="consultation")
    sale.sale_reference = reference
    with pytest.raises(renderer.PurchaseEmailRenderError, match="invalid purchase reference"):
        renderer.render_purchase_email(
            sale, public_base_url="https://app.example.test", now=datetime.now(UTC)
        )
