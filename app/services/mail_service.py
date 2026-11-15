from __future__ import annotations

import smtplib
import ssl
from contextlib import contextmanager, suppress
from email.mime.text import MIMEText

from app.core.config import settings


@contextmanager
def _bounded_smtp(timeout: float):
    server = smtplib.SMTP(
        settings.MAIL_SMTP_HOST, settings.MAIL_SMTP_PORT, timeout=timeout
    )
    try:
        yield server
    finally:
        # Socket cleanup must not change a completed SMTP submission outcome.
        with suppress(OSError):
            server.close()


def send_email(
    to_email: str, subject: str, body: str, *, timeout: float | None = None
) -> None:
    """
    Send email via SMTP (Gmail).
    """

    if not to_email:
        raise ValueError("Recipient email address is not configured.")

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = f"{settings.MAIL_FROM_NAME} <{settings.MAIL_FROM_EMAIL}>"
    msg["To"] = to_email

    connection = (
        smtplib.SMTP(settings.MAIL_SMTP_HOST, settings.MAIL_SMTP_PORT)
        if timeout is None
        else _bounded_smtp(timeout)
    )
    with connection as server:
        if settings.MAIL_SMTP_TLS:
            if timeout is None:
                server.starttls()
            else:
                server.starttls(context=ssl.create_default_context())

        server.login(settings.MAIL_SMTP_USER, settings.MAIL_SMTP_PASSWORD)
        server.send_message(msg)
