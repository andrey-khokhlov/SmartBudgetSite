import re
import secrets

DOWNLOAD_SUPPORT_REFERENCE_PREFIX = "DL-"
DOWNLOAD_SUPPORT_REFERENCE_LENGTH = 8
DOWNLOAD_SUPPORT_REFERENCE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
DOWNLOAD_SUPPORT_REFERENCE_PATTERN = re.compile(
    rf"^{DOWNLOAD_SUPPORT_REFERENCE_PREFIX}"
    rf"[{DOWNLOAD_SUPPORT_REFERENCE_ALPHABET}]"
    rf"{{{DOWNLOAD_SUPPORT_REFERENCE_LENGTH}}}$"
)


def generate_download_support_reference() -> str:
    """Generate a public, non-secret reference for download support."""
    suffix = "".join(
        secrets.choice(DOWNLOAD_SUPPORT_REFERENCE_ALPHABET)
        for _ in range(DOWNLOAD_SUPPORT_REFERENCE_LENGTH)
    )
    return f"{DOWNLOAD_SUPPORT_REFERENCE_PREFIX}{suffix}"


def is_valid_download_support_reference(value: str) -> bool:
    """Return whether a value matches the currently supported public format."""
    return DOWNLOAD_SUPPORT_REFERENCE_PATTERN.fullmatch(value) is not None
