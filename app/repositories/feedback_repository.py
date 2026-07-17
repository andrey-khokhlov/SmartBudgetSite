from sqlalchemy.orm import Session

from app.models.feedback import FeedbackMessage


class FeedbackRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        message_type: str,
        email: str,
        subject: str,
        message: str,
        name: str | None = None,
        page_url: str | None = None,
        user_agent: str | None = None,
        support_reference: str | None = None,
    ) -> FeedbackMessage:
        feedback = FeedbackMessage(
            type=message_type,
            email=email,
            subject=subject,
            message=message,
            name=name,
            page_url=page_url,
            user_agent=user_agent,
            support_reference=support_reference,
        )
        self.db.add(feedback)
        self.db.commit()
        self.db.refresh(feedback)
        return feedback

    def get_recent(self, limit: int = 50):
        return (
            self.db.query(FeedbackMessage)
            .order_by(FeedbackMessage.created_at.desc())
            .limit(limit)
            .all()
        )

    def mark_resolved(self, feedback_id: int) -> FeedbackMessage | None:
        feedback = (
            self.db.query(FeedbackMessage)
            .filter(FeedbackMessage.id == feedback_id)
            .first()
        )

        if not feedback:
            return None

        feedback.is_resolved = True
        self.db.commit()
        self.db.refresh(feedback)

        return feedback
