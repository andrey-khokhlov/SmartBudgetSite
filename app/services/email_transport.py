from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TransactionalEmail:
    recipient: str
    sender_email: str
    sender_name: str
    subject: str
    text_body: str
    html_body: str
    idempotency_key: str


@dataclass(frozen=True)
class EmailTransportResult:
    provider_message_id: str


class EmailTransportError(Exception):
    """Base class for sanitized email transport failures."""


class EmailTransportDefinitiveError(EmailTransportError):
    """The provider definitively rejected or could not accept the request."""


class EmailTransportAmbiguousError(EmailTransportError):
    """The provider may have accepted the request; stable-key retry is required."""


class EmailTransport(Protocol):
    def send(self, email: TransactionalEmail) -> EmailTransportResult: ...
