import re

from app.services import support_reference_service


def test_download_support_reference_uses_safe_public_format():
    reference = support_reference_service.generate_download_support_reference()

    assert re.fullmatch(r"DL-[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{8}", reference)
    assert support_reference_service.is_valid_download_support_reference(reference)


def test_download_support_reference_validation_rejects_ambiguous_or_secret_values():
    assert not support_reference_service.is_valid_download_support_reference(
        "DL-ABCD0O1I"
    )
    assert not support_reference_service.is_valid_download_support_reference(
        "download-token-value"
    )
    assert not support_reference_service.is_valid_download_support_reference(
        "/download/private-token"
    )
