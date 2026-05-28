# main.py
import os
import json
import logging
from pathlib import Path
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
    datefmt="%Y-%m-%d %H:%M:%S"
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

MAX_PROMPT_LENGTH = config("MAX_PROMPT_LENGTH", default=10000, cast=int)
MAX_FILENAME_LENGTH = config("MAX_FILENAME_LENGTH", default=255, cast=int)
ALLOWED_EXTENSIONS = {'.py', '.js', '.ts', '.java', '.cpp', '.c', '.h', '.cs', '.go', '.rs', '.html', '.css'}
# Dedicated target sandbox directory
TARGET_BASE_DIR = Path("generated_components").resolve()


def validate_filename(filename: str) -> bool:
    if not filename or len(filename) > MAX_FILENAME_LENGTH:
        return False
    if '..' in filename or '~' in filename or filename.startswith('/'):
        return False
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS and ext != '':
        return False
    return True


@app.get("/", response_class=HTMLResponse)
async def index_view(request: Request, db: Session = Depends(get_db)):
    history = db.query(models.GenerationHistory).order_by(
        models.GenerationHistory.created_at.desc()
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"history": history}
    )


@app.post("/api/generate")
async def handle_generation(
    request: Request,
    prompt: str = Form(...),
    filename: str = Form(...),
    db: Session = Depends(get_db)
):
    logger.info(f"[INGRESS] Received code generation event interceptor for output component: {filename}")
    
    # Pre-flight validations
    if not prompt.strip() or not filename.strip():
        logger.warning("[VALIDATION] Intercepted empty required arguments.")
        raise HTTPException(status_code=400, detail="Required fields are empty.")
    
    if len(prompt) > MAX_PROMPT_LENGTH:
        logger.warning(f"[VALIDATION] Prompt length boundary limit exceeded: {len(prompt)} chars.")
        raise HTTPException(status_code=400, detail="Prompt exceeds maximum length threshold.")
    
    if not validate_filename(filename):
        logger.warning(f"[SECURITY] Filename failed validation structural analysis: {filename}")
        raise HTTPException(status_code=400, detail="Invalid filename format or extension.")

    # Enforce standard file extension if missing
    if not Path(filename).suffix:
        filename = f"{filename}.py"

    async def event_generator():
        accumulated_chunks = []
        try:
            stream = coder_service.generate_code_stream(prompt)
            
            async for token in stream:
                # Active verification of client lifecycle network link
                if await request.is_disconnected():
                    logger.warning(f"[ABORT] Client link severed. Terminating processing thread safely for: {filename}")
                    return

                accumulated_chunks.append(token)
                # Yield payload conforming to SSE line standard
                yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
            
            full_source_code = "".join(accumulated_chunks)
            if not full_source_code.strip():
                logger.error("[PIPELINE] Generation terminal finished but returned empty buffer string.")
                yield f"data: {json.dumps({'type': 'error', 'detail': 'Zero tokens compiled from remote node.'})}\n\n"
                return

            # Compute safe explicit target subfolder sandbox path
            safe_target_path = (TARGET_BASE_DIR / filename).resolve()
            if not str(safe_target_path).startswith(str(TARGET_BASE_DIR)):
                logger.error(f"[SECURITY] Path traversal escape routine triggered and intercepted: {filename}")
                yield f"data: {json.dumps({'type': 'error', 'detail': 'Security sandbox violation.'})}\n\n"
                return

            # Write assets inside separate folder structure
            logger.info(f"[IO-WRITE] Flushing memory buffer pipeline to disk: {safe_target_path}")
            os.makedirs(safe_target_path.parent, exist_ok=True)
            with open(safe_target_path, "w", encoding="utf-8") as file_handle:
                file_handle.write(full_source_code)

            # Persist tracking history meta log inside relational database
            logger.info("[DATABASE-TX] Committing generation audit records to storage schema.")
            history_entry = models.GenerationHistory(
                prompt=prompt[:500],
                generated_code=full_source_code,
                filename=filename
            )
            db.add(history_entry)
            db.commit()
            db.refresh(history_entry)
            
            logger.info(f"[SUCCESS] Core transaction finalized. Node record tracking index ID: {history_entry.id}")
            
            # Send completion block metadata payload to frontend
            payload = {
                'type': 'final',
                'id': history_entry.id,
                'prompt': history_entry.prompt,
                'filename': history_entry.filename,
                'generated_code': history_entry.generated_code,
                'created_at': history_entry.created_at.strftime('%Y-%m-%d %H:%M:%S')
            }
            yield f"data: {json.dumps(payload)}\n\n"

        except Exception as crash_exception:
            db.rollback()
            logger.error(f"[CRITICAL-FAILURE] Subroutine exception stack trace: {str(crash_exception)}")
            yield f"data: {json.dumps({'type': 'error', 'detail': f'Runtime breakdown: {str(crash_exception)}'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")