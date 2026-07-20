import logging
from logging.config import dictConfig


class StructuredWebhookFormatter(logging.Formatter):
    """Append single-line webhook audit fields when present on a log record."""

    webhook_fields = ("provider", "event_type", "status")

    def format(self, record: logging.LogRecord) -> str:
        formatted_record = super().format(record)
        if not all(hasattr(record, field) for field in self.webhook_fields):
            return formatted_record

        audit_fields = " ".join(
            f"{field}={str(getattr(record, field))!r}"
            for field in self.webhook_fields
        )
        return f"{formatted_record} {audit_fields}"


def setup_logging() -> None:
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "()": StructuredWebhookFormatter,
                    "format": "%(asctime)s %(levelname)s [%(name)s] %(message)s",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                }
            },
            "root": {"level": "INFO", "handlers": ["console"]},
        }
    )
