from datetime import datetime

from pydantic import BaseModel, Field, field_validator


IDENTIFIER_PATTERN = r"^[A-Za-z0-9._:-]+$"


class TaskRegisterRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=64, pattern=IDENTIFIER_PATTERN)
    session_id: str = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)
    task_id: str = Field(min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN)

    title: str = Field(min_length=1, max_length=200)
    public_instruction: str = Field(min_length=1, max_length=4000)
    verification_prompt: str = Field(min_length=20, max_length=12_000)

    minimum_confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    max_attempts: int = Field(default=5, ge=1, le=50)
    cooldown_seconds: int = Field(default=20, ge=0, le=3600)
    expires_in_seconds: int = Field(default=86_400, ge=300, le=604_800)
    reset_result: bool = False

    @field_validator("title", "public_instruction", "verification_prompt")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class TaskRegisterResponse(BaseModel):
    client_id: str
    session_id: str
    task_id: str
    public_token: str
    upload_url: str
    state: str
    expires_at: datetime


class TaskStatusResponse(BaseModel):
    client_id: str
    session_id: str
    task_id: str
    state: str
    solved: bool
    model_solved: bool | None
    confidence: float | None
    reason: str | None
    attempt_count: int
    max_attempts: int
    expires_at: datetime
    updated_at: datetime


class PublicStatusResponse(BaseModel):
    state: str
    solved: bool
    confidence: float | None = None
    reason: str | None = None
    attempt_count: int
    max_attempts: int
    retry_after_seconds: int | None = None


class VerificationResult(BaseModel):
    solved: bool = Field(description="Whether all visible task criteria are clearly satisfied")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in the verdict")
    reason: str = Field(min_length=1, max_length=700, description="Short German explanation")
