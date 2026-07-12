from __future__ import annotations

import smtplib
from email.mime.text import MIMEText

from app.core.config import settings

def send_email(to_email: str, subject: str, body: str) -> None:
    """
    Send email via SMTP (Gmail).
    """

    if not to_email:
        raise ValueError("Recipient email address is not configured.")

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = f"{settings.MAIL_FROM_NAME} <{settings.MAIL_FROM_EMAIL}>"
    msg["To"] = to_email

    with smtplib.SMTP(settings.MAIL_SMTP_HOST, settings.MAIL_SMTP_PORT) as server:
        if settings.MAIL_SMTP_TLS:
            server.starttls()

        server.login(settings.MAIL_SMTP_USER, settings.MAIL_SMTP_PASSWORD)
        server.send_message(msg)