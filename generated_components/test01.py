```python
# main.py
import os
import json
import logging
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from decouple import config

import models
from database import engine, get_db
from services.openrouter_service import OpenRouterCodingService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="OpenRouter Studio Core")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
coder_service = OpenRouterCodingService()

MAX_PROMPT_LENGTH: int = config("MAX_PROMPT_LENGTH", default=10000, cast=int)
MAX_FILENAME_LENGTH: int = config("MAX_FILENAME_LENGTH", default=255, cast=int)
ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py", ".js", ".ts", ".java", ".cpp", ".c", ".h",
        ".cs", ".go", ".rs", ".html", ".css",
    }
)
TARGET_BASE_DIR: Path = Path("generated_components").resolve()


def validate_filename(filename: str) -> bool:
    if not filename or len(filename) > MAX_FILENAME_LENGTH:
        return False
    if ".." in filename or "~" in filename or filename.startswith("/"):
        return False
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS and ext != "":
        return False
    return True


def ensure_safe_path(filename: str) -> Path:
    """Resolve the target path and guarantee it stays inside TARGET_BASE_DIR."""
    safe_target_path: Path = (TARGET_BASE_DIR / filename).resolve()
    if not str(safe_target_path).startswith(str(TARGET_BASE_DIR)):
        raise ValueError(f"Path traversal detected: {filename}")
    return safe_target_path


def ensure_extension(filename: str) -> str:
    """Append a default .py extension when the filename has none."""
    if not Path(filename).suffix:
        return f"{filename}.py"
    return filename


def build_sse_event(event_type: str, payload: dict) -> str:
    """Build a single Server-Sent Events frame."""
    return f"data: {json.dumps({'type': event_type, **payload})}\n\n"


@app.get("/", response_class=HTMLResponse)
async def index_view(
    request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    history = (
        db.query(models.GenerationHistory)
        .order_by(models.GenerationHistory.created_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"history": history},
    )


@app.post("/api/generate")
async def handle_generation(
    request: Request,
    prompt: str = Form(...),
    filename: str = Form(...),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    logger.info(
        "[INGRESS] Received code generation event interceptor for output component: %s",
        filename,
    )

    # --- Pre-flight validations ---
    if not prompt.strip() or not filename.strip():
        logger.warning("[VALIDATION] Intercepted empty required arguments.")
        raise HTTPException(status_code=400, detail="Required fields are empty.")

    if len(prompt) > MAX_PROMPT_LENGTH:
        logger.warning(
            "[VALIDATION] Prompt length boundary limit exceeded: %d chars.",
            len(prompt),
        )
        raise HTTPException(
            status_code=400, detail="Prompt exceeds maximum length threshold."
        )

    if not validate_filename(filename):
        logger.warning(
            "[SECURITY] Filename failed validation structural analysis: %s",
            filename,
        )
        raise HTTPException(
            status_code=400, detail="Invalid filename format or extension."
        )

    filename = ensure_extension(filename)

    async def event_generator() -> AsyncGenerator[str, None]:
        accumulated_chunks: list[str] = []
        try:
            stream = coder_service.generate_code_stream(prompt)

            async for token in stream:
                if await request.is_disconnected():
                    logger.warning(
                        "[ABORT] Client link severed. Terminating processing "
                        "thread safely for: %s",
                        filename,
                    )
                    return

                accumulated_chunks.append(token)
                yield build_sse_event("token", {"content": token})

            full_source_code: str = "".join(accumulated_chunks)
            if not full_source_code.strip():
                logger.error(
                    "[PIPELINE] Generation terminal finished but returned "
                    "empty buffer string.",
                )
                yield build_sse_event(
                    "error",
                    {"detail": "Zero tokens compiled from remote node."},
                )
                return

            try:
                safe_target_path: Path = ensure_safe_path(filename)
            except ValueError:
                logger.error(
                    "[SECURITY] Path traversal escape routine triggered and "
                    "intercepted: %s",
                    filename,
                )
                yield build_sse_event(
                    "error",
                    {"detail": "Security sandbox violation."},
                )
                return

            logger.info(
                "[IO-WRITE] Flushing memory buffer pipeline to disk: %s",
                safe_target_path,
            )
            os.makedirs(safe_target_path.parent, exist_ok=True)
            safe_target_path.write_text(full_source_code, encoding="utf-8")

            # Persist generation record
            record = models.GenerationHistory(
                prompt=prompt,
                filename=filename,
                generated_code=full_source_code,
            )
            db.add(record)
            db.commit()

            yield build_sse_event(
                "done",
                {"detail": f"File written to {safe_target_path}"},
            )

        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("[PIPELINE] Unhandled exception during generation.")
            yield build_sse_event(
                "error",
                {"detail": f"Internal server error: {exc}"},
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```