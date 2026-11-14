import re
import secrets

SALE_REFERENCE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
SALE_REFERENCE_LENGTH = 14
SALE_REFERENCE_PREFIX = "PAY-"
SALE_REFERENCE_PATTERN = re.compile(
    rf"{SALE_REFERENCE_PREFIX}[{SALE_REFERENCE_ALPHABET}]{{{SALE_REFERENCE_LENGTH}}}"
)


def generate_sale_reference() -> str:
    suffix = "".join(
        secrets.choice(SALE_REFERENCE_ALPHABET) for _ in range(SALE_REFERENCE_LENGTH)
    )
    return f"{SALE_REFERENCE_PREFIX}{suffix}"
