from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class FeedbackMessageType(str, Enum):
    SITE_ISSUE = "site_issue"
    GENERAL_QUESTION = "general_question"
    PRODUCT_FEEDBACK = "product_feedback"
    PURCHASE_OR_DOWNLOAD_ISSUE = "purchase_or_download_issue"


class FeedbackCreate(BaseModel):
    message_type: FeedbackMessageType
    email: EmailStr | None = None
    subject: str = Field(..., min_length=3, max_length=200)
    message: str = Field(..., min_length=10, max_length=2000)
    name: str | None = Field(default=None, max_length=200)
    page_url: str | None = None

    model_config = ConfigDict(
        str_strip_whitespace=True,
    )

    @model_validator(mode="after")
    def validate_product_feedback_fields(self):
        if self.message_type == FeedbackMessageType.PRODUCT_FEEDBACK:
            if not self.email:
                raise ValueError("Email is required for product feedback.")
        return self


class FeedbackCreateResponse(BaseModel):
    status: str
    id: int


class FeedbackItemResponse(BaseModel):
    id: int
    type: str
    email: EmailStr
    subject: str
    message: str
    name: str | None = None
    page_url: str | None = None
    user_agent: str | None = None
    is_resolved: bool
    created_at: datetime

    model_config = {
        "from_attributes": True,
    }


class FeedbackListResponse(BaseModel):
    items: list[FeedbackItemResponse]
    count: int
