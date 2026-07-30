import logging
import re
from logging.config import dictConfig

REDACTED_CAPABILITY = "[REDACTED]"
CAPABILITY_TARGET_PATTERNS = (
    re.compile(r"(?i)(/download/)([^/?#\s]+)"),
    re.compile(r"(?i)(/consultation/book/)([^/?#\s]+)"),
    re.compile(r"(?i)(%2fdownload%2f)([^/?&#\s]+?)(?=%2f|[/?&#\s]|$)"),
    re.compile(r"(?i)(%2fconsultation%2fbook%2f)([^/?&#\s]+?)(?=%2f|[/?&#\s]|$)"),
)


def sanitize_access_log_target(target: str) -> str:
    """Remove query data and redact capability segments from an access target."""
    sanitized = target.split("?", 1)[0]
    for pattern in CAPABILITY_TARGET_PATTERNS:
        sanitized = pattern.sub(
            lambda match: f"{match.group(1)}{REDACTED_CAPABILITY}",
            sanitized,
        )
    return sanitized


class SanitizeUvicornAccessFilter(logging.Filter):
    """Sanitize Uvicorn's request-target argument before formatting."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "uvicorn.access":
            return True

        if isinstance(record.args, tuple) and len(record.args) >= 3:
            arguments = list(record.args)
            arguments[2] = sanitize_access_log_target(str(arguments[2]))
            record.args = tuple(arguments)

        return True


class StructuredWebhookFormatter(logging.Formatter):
    """Append approved structured audit fields when present on a log record."""

    webhook_fields = ("provider", "event_type", "status")
    rate_limit_fields = (
        "policy_name",
        "method",
        "route_template",
        "identity_kind",
        "status",
    )
    optional_rate_limit_fields = ("retry_after", "provider")
    release_workflow_fields = (
        "operation_id",
        "product_id",
        "workflow_phase",
        "storage_provider",
        "outcome",
        "storage_key_digest",
    )

    def format(self, record: logging.LogRecord) -> str:
        formatted_record = super().format(record)
        if all(hasattr(record, field) for field in self.release_workflow_fields):
            audit_fields = " ".join(
                f"{field}={str(getattr(record, field))!r}"
                for field in self.release_workflow_fields
            )
            return f"{formatted_record} {audit_fields}"

        if all(hasattr(record, field) for field in self.rate_limit_fields):
            fields = list(self.rate_limit_fields)
            fields.extend(
                field
                for field in self.optional_rate_limit_fields
                if hasattr(record, field)
            )
            audit_fields = " ".join(
                f"{field}={str(getattr(record, field))!r}" for field in fields
            )
            return f"{formatted_record} {audit_fields}"

        if not all(hasattr(record, field) for field in self.webhook_fields):
            return formatted_record

        audit_fields = " ".join(
            f"{field}={str(getattr(record, field))!r}" for field in self.webhook_fields
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
            "filters": {
                "sanitize_uvicorn_access": {
                    "()": SanitizeUvicornAccessFilter,
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                },
                "uvicorn_access_console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "filters": ["sanitize_uvicorn_access"],
                    "stream": "ext://sys.stdout",
                },
            },
            "loggers": {
                "uvicorn.access": {
                    "handlers": ["uvicorn_access_console"],
                    "level": "INFO",
                    "propagate": False,
                }
            },
            "root": {"level": "INFO", "handlers": ["console"]},
        }
    )
