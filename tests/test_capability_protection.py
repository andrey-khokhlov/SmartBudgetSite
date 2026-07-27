import io
import logging

import pytest

from app.core.capability_protection import is_capability_path
from app.core.logging import SanitizeUvicornAccessFilter


def _format_uvicorn_access_target(target: str) -> str:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(SanitizeUvicornAccessFilter())
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("uvicorn.access")
    original_handlers = logger.handlers[:]
    original_propagate = logger.propagate
    original_level = logger.level
    try:
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(logging.INFO)
        logger.info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:12345",
            "GET",
            target,
            "1.1",
            200,
        )
        return stream.getvalue()
    finally:
        logger.handlers = original_handlers
        logger.propagate = original_propagate
        logger.setLevel(original_level)


@pytest.mark.parametrize(
    "path",
    [
        "/download/download-secret",
        "/consultation/book/booking-secret",
    ],
)
def test_capability_path_detection_accepts_protected_routes(path):
    assert is_capability_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "/download",
        "/consultation/book",
        "/products",
    ],
)
def test_capability_path_detection_ignores_ordinary_routes(path):
    assert not is_capability_path(path)


@pytest.mark.parametrize(
    ("target", "secret", "expected_path"),
    [
        (
            "/download/download-secret?lang=ru",
            "download-secret",
            "/download/[REDACTED]",
        ),
        (
            "/consultation/book/booking-secret?next=/products",
            "booking-secret",
            "/consultation/book/[REDACTED]",
        ),
        (
            "/forward/download/embedded-secret/continue?debug=true",
            "embedded-secret",
            "/forward/download/[REDACTED]/continue",
        ),
        (
            "/forward%2Fconsultation%2Fbook%2Fencoded-secret%2Fcontinue",
            "encoded-secret",
            "/forward%2Fconsultation%2Fbook%2F[REDACTED]%2Fcontinue",
        ),
    ],
)
def test_uvicorn_access_output_redacts_capabilities_and_queries(
    target,
    secret,
    expected_path,
):
    output = _format_uvicorn_access_target(target)

    assert secret not in output
    assert "?" not in output
    assert expected_path in output
    assert "127.0.0.1:12345" in output
    assert "GET" in output
    assert "HTTP/1.1" in output
    assert "200" in output


def test_uvicorn_access_output_keeps_ordinary_path_readable_without_query():
    output = _format_uvicorn_access_target("/products/smartbudget?lang=ru")

    assert "/products/smartbudget" in output
    assert "lang=ru" not in output
    assert "[REDACTED]" not in output
