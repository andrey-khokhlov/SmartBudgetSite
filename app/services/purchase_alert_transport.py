import json
import re
import smtplib
import ssl
from contextlib import suppress
from email.message import EmailMessage
from http.client import HTTPException, HTTPSConnection

from app.core.config import settings

NETWORK_TIMEOUT = 5


def send_telegram_alert(message: str) -> str | None:
    token = settings.TELEGRAM_BOT_TOKEN or ""
    if (
        not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token)
        or not settings.TELEGRAM_CHAT_ID
    ):
        return "configuration"
    # Avoid HTTP client request logging because the Bot API embeds its token in the path.
    connection = HTTPSConnection("api.telegram.org", timeout=NETWORK_TIMEOUT)
    try:
        connection.request(
            "POST",
            f"/bot{token}/sendMessage",
            body=json.dumps({"chat_id": settings.TELEGRAM_CHAT_ID, "text": message}),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        if response.status in (408, 429) or response.status >= 500:
            return "temporary"
        if response.status >= 400:
            return "permanent"
        if not 200 <= response.status < 300:
            return "ambiguous"
        body = json.loads(response.read(16 * 1024))
        if isinstance(body, dict) and body.get("ok") is True:
            return None
        return "ambiguous"
    except (HTTPException, OSError, ValueError, RecursionError):
        return "ambiguous"
    finally:
        connection.close()


def send_smtp_alert(message: str) -> str | None:
    if not settings.MAIL_SMTP_TLS or not all(
        (
            settings.MAIL_SMTP_HOST,
            settings.MAIL_SMTP_USER,
            settings.MAIL_SMTP_PASSWORD,
            settings.MAIL_FROM_EMAIL,
            settings.ADMIN_NOTIFICATION_EMAIL,
        )
    ):
        return "configuration"
    try:
        mail = EmailMessage()
        mail["Subject"] = "SmartBudget purchase delivery incident"
        mail["From"] = settings.MAIL_FROM_EMAIL
        mail["To"] = settings.ADMIN_NOTIFICATION_EMAIL
        mail.set_content(message)
        server = smtplib.SMTP(
            settings.MAIL_SMTP_HOST, settings.MAIL_SMTP_PORT, timeout=NETWORK_TIMEOUT
        )
        try:
            server.starttls(context=ssl.create_default_context())
            server.login(settings.MAIL_SMTP_USER, settings.MAIL_SMTP_PASSWORD)
            server.send_message(mail)
        finally:
            # Socket cleanup cannot change the result of the SMTP transaction.
            with suppress(OSError, smtplib.SMTPException):
                server.close()
    except smtplib.SMTPRecipientsRefused as exc:
        return (
            "temporary"
            if any(400 <= code < 500 for code, _ in exc.recipients.values())
            else "permanent"
        )
    except smtplib.SMTPResponseException as exc:
        return "temporary" if 400 <= exc.smtp_code < 500 else "permanent"
    except (smtplib.SMTPNotSupportedError, ssl.SSLCertVerificationError):
        return "configuration"
    except (OSError, smtplib.SMTPException):
        return "ambiguous"
    except ValueError:
        return "configuration"
    return None
