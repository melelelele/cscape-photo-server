import logging
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.auth import require_service_key
from app.config import Settings, get_settings
from app.database import Base, engine, get_db
from app.image_processing import normalize_uploaded_image
from app.models import PhotoTask
from app.schemas import (
    PublicStatusResponse,
    TaskRegisterRequest,
    TaskRegisterResponse,
    TaskStatusResponse,
)
from app.xai_client import XAIServiceError, verify_image


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="CSCape Photo Verification Service",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"service": "cscape-photo-server", "status": "ok"}


@app.get("/healthz", include_in_schema=False)
def healthz(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.post(
    "/api/v1/tasks",
    response_model=TaskRegisterResponse,
    dependencies=[Depends(require_service_key)],
)
def register_task(
    payload: TaskRegisterRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TaskRegisterResponse:
    task = db.scalar(
        select(PhotoTask).where(
            PhotoTask.client_id == payload.client_id,
            PhotoTask.session_id == payload.session_id,
            PhotoTask.task_id == payload.task_id,
        )
    )

    expires_at = datetime.now(UTC) + timedelta(seconds=payload.expires_in_seconds)

    if task is None:
        task = PhotoTask(
            public_token=secrets.token_urlsafe(32),
            client_id=payload.client_id,
            session_id=payload.session_id,
            task_id=payload.task_id,
            title=payload.title,
            public_instruction=payload.public_instruction,
            verification_prompt=payload.verification_prompt,
            minimum_confidence=payload.minimum_confidence,
            max_attempts=payload.max_attempts,
            cooldown_seconds=payload.cooldown_seconds,
            expires_at=expires_at,
        )
        db.add(task)
    else:
        task.title = payload.title
        task.public_instruction = payload.public_instruction
        task.verification_prompt = payload.verification_prompt
        task.minimum_confidence = payload.minimum_confidence
        task.max_attempts = payload.max_attempts
        task.cooldown_seconds = payload.cooldown_seconds
        task.expires_at = expires_at

        if payload.reset_result:
            _reset_task_result(task)

    db.commit()
    db.refresh(task)

    return TaskRegisterResponse(
        client_id=task.client_id,
        session_id=task.session_id,
        task_id=task.task_id,
        public_token=task.public_token,
        upload_url=f"{settings.public_base_url}/u/{task.public_token}",
        state=_effective_state(task),
        expires_at=task.expires_at,
    )


@app.get(
    "/api/v1/tasks/status",
    response_model=TaskStatusResponse,
    dependencies=[Depends(require_service_key)],
)
def task_status(
    client_id: str,
    session_id: str,
    task_id: str,
    db: Session = Depends(get_db),
) -> TaskStatusResponse:
    task = _get_task_by_identity(db, client_id, session_id, task_id)
    return _task_status_response(task)


@app.get("/u/{public_token}", response_class=HTMLResponse, include_in_schema=False)
def upload_page(
    request: Request,
    public_token: str,
    db: Session = Depends(get_db),
):
    task = _get_task_by_token(db, public_token)
    return templates.TemplateResponse(
        request=request,
        name="upload.html",
        context={
            "task": task,
            "effective_state": _effective_state(task),
        },
    )


@app.get(
    "/api/v1/public/{public_token}/status",
    response_model=PublicStatusResponse,
    include_in_schema=False,
)
def public_status(
    public_token: str,
    db: Session = Depends(get_db),
) -> PublicStatusResponse:
    task = _get_task_by_token(db, public_token)
    return _public_status_response(task)


@app.post(
    "/api/v1/public/{public_token}/submit",
    response_model=PublicStatusResponse,
    include_in_schema=False,
)
async def submit_photo(
    public_token: str,
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PublicStatusResponse:
    normalized_image = await normalize_uploaded_image(image, settings)

    task = db.scalar(
        select(PhotoTask)
        .where(PhotoTask.public_token == public_token)
        .with_for_update()
    )
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    now = datetime.now(UTC)
    if task.solved:
        db.rollback()
        return _public_status_response(task)

    _assert_task_accepts_attempt(task, now, settings)

    task.state = "checking"
    task.attempt_count += 1
    task.last_attempt_at = now
    task.last_error = None
    db.commit()
    task_id = task.id
    verification_prompt = task.verification_prompt
    minimum_confidence = task.minimum_confidence

    try:
        verdict = await verify_image(
            image_bytes=normalized_image,
            verification_prompt=verification_prompt,
            settings=settings,
        )
    except XAIServiceError as exc:
        logger.warning("Photo verification failed for task %s: %s", task_id, exc)
        failed_task = db.scalar(
            select(PhotoTask).where(PhotoTask.id == task_id).with_for_update()
        )
        if failed_task is not None:
            failed_task.state = "error"
            failed_task.last_error = str(exc)
            failed_task.reason = "Der Prüfdienst ist momentan nicht erreichbar. Bitte erneut versuchen."
            failed_task.attempt_count = max(0, failed_task.attempt_count - 1)
            failed_task.last_attempt_at = None
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Image verification service is temporarily unavailable",
        ) from exc

    completed_task = db.scalar(
        select(PhotoTask).where(PhotoTask.id == task_id).with_for_update()
    )
    if completed_task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    completed_task.model_solved = verdict.solved
    completed_task.confidence = verdict.confidence
    completed_task.reason = verdict.reason
    completed_task.last_error = None
    completed_task.solved = verdict.solved and verdict.confidence >= minimum_confidence
    completed_task.state = "solved" if completed_task.solved else "rejected"
    db.commit()
    db.refresh(completed_task)

    return _public_status_response(completed_task)


def _get_task_by_identity(
    db: Session,
    client_id: str,
    session_id: str,
    task_id: str,
) -> PhotoTask:
    task = db.scalar(
        select(PhotoTask).where(
            PhotoTask.client_id == client_id,
            PhotoTask.session_id == session_id,
            PhotoTask.task_id == task_id,
        )
    )
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


def _get_task_by_token(db: Session, public_token: str) -> PhotoTask:
    task = db.scalar(select(PhotoTask).where(PhotoTask.public_token == public_token))
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


def _assert_task_accepts_attempt(task: PhotoTask, now: datetime, settings: Settings) -> None:
    if task.expires_at <= now:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Task has expired")
    if task.state == "checking":
        stale_after = timedelta(seconds=settings.xai_timeout_seconds + 30)
        is_stale = (
            task.last_attempt_at is not None
            and task.last_attempt_at + stale_after <= now
        )
        if is_stale:
            task.state = "error"
            task.attempt_count = max(0, task.attempt_count - 1)
            task.last_attempt_at = None
            task.last_error = "Recovered stale verification attempt"
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An image is already being checked",
            )
    if task.attempt_count >= task.max_attempts:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="No attempts remaining")
    if task.last_attempt_at is not None:
        retry_at = task.last_attempt_at + timedelta(seconds=task.cooldown_seconds)
        if retry_at > now:
            retry_after = max(1, int((retry_at - now).total_seconds()))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"message": "Please wait before trying again", "retry_after_seconds": retry_after},
            )


def _effective_state(task: PhotoTask) -> str:
    if task.expires_at <= datetime.now(UTC):
        return "expired"
    return task.state


def _public_status_response(task: PhotoTask) -> PublicStatusResponse:
    retry_after: int | None = None
    now = datetime.now(UTC)
    if task.last_attempt_at is not None and not task.solved:
        retry_at = task.last_attempt_at + timedelta(seconds=task.cooldown_seconds)
        if retry_at > now:
            retry_after = max(1, int((retry_at - now).total_seconds()))

    return PublicStatusResponse(
        state=_effective_state(task),
        solved=task.solved,
        confidence=task.confidence,
        reason=task.reason,
        attempt_count=task.attempt_count,
        max_attempts=task.max_attempts,
        retry_after_seconds=retry_after,
    )


def _task_status_response(task: PhotoTask) -> TaskStatusResponse:
    return TaskStatusResponse(
        client_id=task.client_id,
        session_id=task.session_id,
        task_id=task.task_id,
        state=_effective_state(task),
        solved=task.solved,
        model_solved=task.model_solved,
        confidence=task.confidence,
        reason=task.reason,
        attempt_count=task.attempt_count,
        max_attempts=task.max_attempts,
        expires_at=task.expires_at,
        updated_at=task.updated_at,
    )


def _reset_task_result(task: PhotoTask) -> None:
    task.state = "waiting"
    task.model_solved = None
    task.solved = False
    task.confidence = None
    task.reason = None
    task.last_error = None
    task.attempt_count = 0
    task.last_attempt_at = None
