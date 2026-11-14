import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.services import purchase_email_renderer as renderer
from app.services.payment_reconciliation_service import reconcile_payment_event
from tests.services.test_purchase_email_delivery_service import (
    create_pending_sale,
    payment_event,
)


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
    assert "**Subject:** " + renderer.LINK_MARKER.sub(r"[\2]", template) == approved


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
    ],
)
def test_renderer_rejects_invalid_template(
    db_session, tmp_path, monkeypatch, kind, body
):
    sale = create_pending_sale(db_session, kind=kind)
    reconcile_payment_event(db_session, payment_event(sale))
    db_session.commit()
    monkeypatch.setattr(renderer, "TEMPLATE_DIRECTORY", tmp_path)
    (tmp_path / f"{kind}_en.txt").write_text(
        f"Subject\n\n{body}\n\n{{{{ sale_reference }}}}", encoding="utf-8"
    )

    with pytest.raises(renderer.PurchaseEmailRenderError, match="template"):
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
        'Subject\n\n[[booking:**<script> & "book"**]]\n\n{{ sale_reference }}',
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
        f"Subject\n\n[[booking:Book]]\n\n{placeholder}", encoding="utf-8"
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
