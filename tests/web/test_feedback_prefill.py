import pytest


@pytest.mark.parametrize(
    ("lang", "expected_label", "expected_type"),
    [
        ("en", "Support reference", "Purchase or download issue"),
        ("ru", "Номер обращения", "Проблема с покупкой или скачиванием"),
    ],
)
def test_feedback_get_prefills_valid_support_context(
    client,
    lang,
    expected_label,
    expected_type,
):
    response = client.get(
        "/feedback",
        params={
            "lang": lang,
            "message_type": "purchase_or_download_issue",
            "support_reference": "DL-ABCDEFGH",
        },
    )

    assert response.status_code == 200
    assert expected_label in response.text
    assert expected_type in response.text
    assert 'value="purchase_or_download_issue" selected' in response.text
    assert 'value="DL-ABCDEFGH"' in response.text
    assert 'name="support_reference"' in response.text
    assert "readonly" in response.text


def test_feedback_get_ignores_invalid_prefill_values(client):
    response = client.get(
        "/feedback",
        params={
            "message_type": "<script>alert(1)</script>",
            "support_reference": "/download/private-token",
        },
    )

    assert response.status_code == 200
    assert "<script>alert(1)</script>" not in response.text
    assert "/download/private-token" not in response.text
    assert 'name="support_reference"' not in response.text


def test_feedback_get_ignores_invalid_reference_for_supported_type(client):
    response = client.get(
        "/feedback",
        params={
            "message_type": "purchase_or_download_issue",
            "support_reference": "DL-ABCD0O1I",
        },
    )

    assert response.status_code == 200
    assert 'value="purchase_or_download_issue" selected' in response.text
    assert "DL-ABCD0O1I" not in response.text
    assert 'name="support_reference"' not in response.text


def test_feedback_form_uses_one_email_field_for_private_feedback(client):
    response = client.get("/feedback?message_type=purchase_or_download_issue")

    assert response.status_code == 200
    assert 'id="email" name="email"' in response.text
    assert 'name="contact_email"' not in response.text
