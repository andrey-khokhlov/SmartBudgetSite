from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class FeedbackAdminListItem(BaseModel):
    """
    Lightweight schema for feedback list page.

    Used to display a compact list of messages in the internal backoffice UI.
    """

    id: int
    created_at: datetime
    message_type: str
    email: str
    subject: str
    is_resolved: bool
    support_reference: str | None = None


class FeedbackAdminDetail(BaseModel):
    """
    Full schema for feedback detail page.

    Used when opening one specific feedback message in the internal backoffice UI.
    """

    id: int
    created_at: datetime
    message_type: str
    name: str | None
    email: str
    subject: str
    message: str
    page_url: str | None
    user_agent: str | None
    is_resolved: bool
    support_reference: str | None = None


class FeedbackResolveUpdate(BaseModel):
    """
    Schema for updating feedback resolution status.
    """

    is_resolved: bool
