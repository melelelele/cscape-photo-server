import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PhotoTask(Base):
    __tablename__ = "photo_tasks"
    __table_args__ = (
        UniqueConstraint(
            "client_id",
            "session_id",
            "task_id",
            name="uq_photo_task_identity",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    public_token: Mapped[str] = mapped_column(String(128), unique=True, index=True)

    client_id: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    task_id: Mapped[str] = mapped_column(String(128), index=True)

    title: Mapped[str] = mapped_column(String(200))
    public_instruction: Mapped[str] = mapped_column(Text)
    verification_prompt: Mapped[str] = mapped_column(Text)

    minimum_confidence: Mapped[float] = mapped_column(Float, default=0.85)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=20)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)

    state: Mapped[str] = mapped_column(String(20), default="waiting", index=True)
    model_solved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    solved: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
