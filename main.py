# main.py

import os
import json
import logging
import threading
import time
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request, Depends, HTTPException, Form, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from decouple import config
from pydantic import BaseModel, Field

# ── Database ────────────────────────────────────────
from database import (
    init_db, check_connection, get_db, DB_ENGINE, 
    engine, SessionLocal, auto_sync_if_needed,
    sync_sqlite_to_postgres, sync_postgres_to_sqlite
)

# ── Models ──────────────────────────────────────────
import models

# ── Services ───────────────────────────────────────
from services.openrouter_service import OpenRouterCodingService
from services.chat_service import ChatService
from services.instruction_service import InstructionService
from services.file_service import FileService

# ── Logging ─────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# ── Initialize Database ─────────────────────────────
logger.info(f"[INIT] Database engine: {DB_ENGINE}")
init_db()
check_connection()

# ── Initialize default instruction on startup ───────
db_init = SessionLocal()
try:
    instruction_service_init = InstructionService(db_init)
    instruction_service_init.initialize_default_instruction()
finally:
    db_init.close()

# ── App Configuration ───────────────────────────────
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

# ── Services ────────────────────────────────────────
coder_service = OpenRouterCodingService()

# ── Global Variables ────────────────────────────────
MAX_PROMPT_LENGTH = config("MAX_PROMPT_LENGTH", default=200000, cast=int)
MAX_CHARS = config("MAX_CHARS", default=200000, cast=int)
MAX_FILENAME_LENGTH = config("MAX_FILENAME_LENGTH", default=255, cast=int)
ALLOWED_EXTENSIONS = {'.py', '.js', '.ts', '.java', '.cpp', '.c', '.h', '.cs', '.go', '.rs', '.html', '.css', '.txt'}
TARGET_BASE_DIR = Path("generated_components").resolve()

# ── Cancellation Events ─────────────────────────────
_cancel_events: dict[int, threading.Event] = {}
_cancel_lock = threading.Lock()


# ── Pydantic Models ─────────────────────────────────
class ChatRenamePayload(BaseModel):
    title: str = Field(..., min_length=1, max_length=128)


class ChatSendPayload(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=100000)


class InstructionPayload(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)  # ✨ اصلاح شده
    is_active: bool = Field(default=True)


class InstructionUpdatePayload(BaseModel):
    title: str = Field(default=None, min_length=1, max_length=255)
    content: str = Field(default=None, min_length=1)  # ✨ اصلاح شده
    is_active: bool = Field(default=None)



# ── Helper Functions ────────────────────────────────
def validate_filename(filename: str) -> bool:
    if not filename or len(filename) > MAX_FILENAME_LENGTH:
        return False
    if '..' in filename or '~' in filename or filename.startswith('/'):
        return False
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS and ext != '':
        return False
    return True


def get_active_instruction_content(db: Session) -> str:
    """Get the active system instruction content from database."""
    service = InstructionService(db)
    instruction = service.get_active_instruction()
    if instruction:
        return instruction.content
    return ""


# ── Background Task ─────────────────────────────────
def run_llm_in_background(message_id: int, messages_payload: list, model_name: str, api_key: str, base_url: str) -> None:
    """Run LLM call in a separate thread to not block the server."""
    import threading as th
    
    def _run():
        from openai import OpenAI
        import httpx
        
        logger.info(f"[BG-TASK-START] message_id={message_id} model={model_name}")
        
        cancel_event = threading.Event()
        with _cancel_lock:
            _cancel_events[message_id] = cancel_event
        
        db = SessionLocal()
        http_client = None
        
        try:
            logger.info(f"[BG-TASK-DB] message_id={message_id} DB session acquired")
            
            if cancel_event.is_set():
                logger.info(f"[BG-TASK-CANCELLED] message_id={message_id}")
                chat_svc = ChatService(db)
                chat_svc.update_message_content(message_id, "⏹ Generation stopped by user.", status="cancelled")
                return
            
            http_client = httpx.Client(
                timeout=httpx.Timeout(
                    connect=30.0,
                    read=600.0,
                    write=30.0,
                    pool=None
                )
            )
            
            client = OpenAI(
                base_url=base_url,
                api_key=api_key,
                http_client=http_client,
                max_retries=2,
                default_headers={"HTTP-Referer": "https://localhost:8000"}
            )
            
            logger.info(f"[BG-TASK-CALLING] message_id={message_id} calling API...")
            t0 = time.time()
            
            response = client.chat.completions.create(
                model=model_name,
                messages=messages_payload,
                temperature=0.3,
                max_tokens=32000,
                stream=False
            )
            
            elapsed = time.time() - t0
            logger.info(f"[BG-TASK-RESPONSE] message_id={message_id} elapsed={elapsed:.1f}s")
            
            if cancel_event.is_set():
                logger.info(f"[BG-TASK-CANCELLED] message_id={message_id} cancelled after API call")
                chat_svc = ChatService(db)
                chat_svc.update_message_content(message_id, "⏹ Generation stopped by user.", status="cancelled")
                return
            
            if not response:
                raise ValueError("Empty response object from API")
            
            if not response.choices or len(response.choices) == 0:
                raise ValueError("No choices in response from API")
            
            if response.choices[0].message is None:
                raise ValueError("Message is None in response")
            
            if response.choices[0].message.content is None:
                finish_reason = response.choices[0].finish_reason if hasattr(response.choices[0], 'finish_reason') else 'unknown'
                logger.warning(f"[BG-TASK] Content is None, finish_reason={finish_reason}")
                if finish_reason == 'length':
                    raise ValueError("Response truncated due to max_tokens limit.")
                else:
                    raise ValueError(f"Content is None, finish_reason={finish_reason}")
            
            reply = response.choices[0].message.content.strip()
            
            if not reply:
                raise ValueError("Response content is empty after strip")
            
            tokens = response.usage.completion_tokens if response.usage else 0
            
            chat_svc = ChatService(db)
            chat_svc.update_message_content(message_id, reply, status="done")
            logger.info(f"[BG-TASK-DONE] message_id={message_id} tokens={tokens} chars={len(reply)}")
            
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)
            logger.error(f"[BG-TASK-ERROR] message_id={message_id} {error_type}: {error_msg}")
            try:
                chat_svc = ChatService(db)
                if "JSONDecodeError" in error_type:
                    user_msg = "⚠️ API response format error. Please try again."
                elif "timeout" in error_msg.lower():
                    user_msg = "⚠️ Request timed out. Try a shorter prompt."
                elif "rate limit" in error_msg.lower():
                    user_msg = "⚠️ Rate limit reached. Please wait a moment."
                else:
                    user_msg = f"⚠️ Error: {error_msg[:200]}"
                chat_svc.update_message_content(message_id, user_msg, status="error")
            except Exception as db_err:
                logger.error(f"[BG-TASK-DB-ERROR] Failed to update error message: {db_err}")
        finally:
            if http_client:
                try:
                    http_client.close()
                except:
                    pass
            db.close()
            with _cancel_lock:
                _cancel_events.pop(message_id, None)
            logger.info(f"[BG-TASK-CLEANUP] message_id={message_id} completed")
    
    t = th.Thread(target=_run, daemon=True)
    t.start()


# ═══════════════════════════════════════════════════════
# ── API Endpoints ───────────────────────────────────
# ═══════════════════════════════════════════════════════

# ── Config ──────────────────────────────────────────
@app.get("/api/config")
async def get_config():
    """Get frontend configuration."""
    return {
        "max_prompt_length": MAX_PROMPT_LENGTH,
        "max_chars": MAX_CHARS,
        "db_engine": DB_ENGINE
    }


# ── Database Sync API ───────────────────────────────
@app.post("/api/sync-to-postgres")
async def api_sync_to_postgres():
    """Manually trigger sync from SQLite to PostgreSQL."""
    try:
        sync_sqlite_to_postgres()
        return {"status": "success", "message": "Synced SQLite → PostgreSQL"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sync-to-sqlite")
async def api_sync_to_sqlite():
    """Manually trigger sync from PostgreSQL to SQLite."""
    try:
        sync_postgres_to_sqlite()
        return {"status": "success", "message": "Synced PostgreSQL → SQLite"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/db-status")
async def db_status():
    """Get database status."""
    from sqlalchemy import text
    
    sqlite_count = 0
    pg_count = 0
    
    try:
        sqlite_engine = create_engine(f"sqlite:///{config('SQLITE_PATH', default='./openrouter_studio.db')}", connect_args={"check_same_thread": False})
        with sqlite_engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM chat_sessions"))
            sqlite_count = result.scalar()
    except:
        pass
    
    try:
        pg_engine = create_engine(
            f"postgresql://{config('POSTGRES_USER')}:{config('POSTGRES_PASSWORD')}@{config('POSTGRES_HOST')}:{config('POSTGRES_PORT')}/{config('POSTGRES_DB')}",
            pool_pre_ping=True
        )
        with pg_engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM chat_sessions"))
            pg_count = result.scalar()
    except:
        pass
    
    return {
        "current_engine": DB_ENGINE,
        "sqlite_sessions": sqlite_count,
        "postgres_sessions": pg_count
    }

@app.post("/api/chat/{session_id}/compress")
async def compress_chat_history(session_id: int, db: Session = Depends(get_db)):
    """فشرده‌سازی تهاجمی تاریخچه برای آزاد کردن context"""
    chat_manager = ChatService(db)
    
    # قبل از فشرده‌سازی، وضعیت رو بگو
    messages = chat_manager.get_session_messages(session_id)
    total_chars = sum(len(m.content or '') for m in messages)
    estimated_tokens = total_chars // 4
    
    # فشرده‌سازی
    new_chars = chat_manager.aggressive_compress(session_id)
    new_tokens = new_chars // 4
    
    return {
        "status": "success",
        "message": f"Compressed {len(messages)} messages",
        "before_tokens": estimated_tokens,
        "after_tokens": new_tokens,
        "saved_tokens": estimated_tokens - new_tokens
    }
# ── Pages ───────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index_view(request: Request, db: Session = Depends(get_db)):
    chat_manager = ChatService(db)
    recent_chats = chat_manager.get_recent_sessions(limit=20)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"recent_chats": recent_chats, "active_session_id": None, "messages": []}
    )


@app.get("/chat/{session_id}", response_class=HTMLResponse)
async def continue_chat_view(session_id: int, request: Request, db: Session = Depends(get_db)):
    chat_manager = ChatService(db)
    recent_chats = chat_manager.get_recent_sessions(limit=20)
    messages = chat_manager.get_session_messages(session_id)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"recent_chats": recent_chats, "active_session_id": session_id, "messages": messages}
    )


# ── Chat Messages ───────────────────────────────────
@app.get("/api/chat/{session_id}/messages")
async def get_chat_messages_json(session_id: int, db: Session = Depends(get_db)):
    chat_manager = ChatService(db)
    messages = chat_manager.get_session_messages(session_id)
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "status": getattr(m, 'status', 'done'),
            "filename": getattr(m, 'filename', None)
        }
        for m in messages
    ]


# ── Session Management ──────────────────────────────
@app.post("/api/chat/new")
async def create_new_chat_session(db: Session = Depends(get_db)):
    chat_manager = ChatService(db)
    new_session = chat_manager.create_session()
    return {"status": "success", "session_id": new_session.id}


@app.post("/api/chat/{session_id}/rename")
async def rename_chat_session(session_id: int, payload: ChatRenamePayload, db: Session = Depends(get_db)):
    chat_manager = ChatService(db)
    if chat_manager.rename_session(session_id, payload.title.strip()):
        return {"status": "success", "message": "Session renamed successfully."}
    raise HTTPException(status_code=404, detail="Session not found.")


@app.post("/api/chat/{session_id}/delete")
async def delete_chat_session(session_id: int, db: Session = Depends(get_db)):
    chat_manager = ChatService(db)
    if chat_manager.delete_session(session_id):
        return {"status": "success", "message": "Session deleted successfully."}
    raise HTTPException(status_code=404, detail="Session not found.")


# ── System Instructions ─────────────────────────────
@app.get("/api/instructions")
async def get_all_instructions(db: Session = Depends(get_db)):
    service = InstructionService(db)
    instructions = service.get_all_instructions()
    return [
        {
            "id": inst.id,
            "title": inst.title,
            "content": inst.content,
            "is_active": inst.is_active,
            "created_at": inst.created_at.isoformat(),
            "updated_at": inst.updated_at.isoformat()
        }
        for inst in instructions
    ]


@app.get("/api/instructions/active")
async def get_active_instruction(db: Session = Depends(get_db)):
    service = InstructionService(db)
    instruction = service.get_active_instruction()
    if not instruction:
        instruction = service.initialize_default_instruction()
    return {
        "id": instruction.id,
        "title": instruction.title,
        "content": instruction.content,
        "is_active": instruction.is_active,
        "created_at": instruction.created_at.isoformat(),
        "updated_at": instruction.updated_at.isoformat()
    }


@app.get("/api/instructions/{instruction_id}")
async def get_instruction_by_id(instruction_id: int, db: Session = Depends(get_db)):
    service = InstructionService(db)
    instruction = service.get_instruction_by_id(instruction_id)
    if not instruction:
        raise HTTPException(status_code=404, detail="Instruction not found.")
    return {
        "id": instruction.id,
        "title": instruction.title,
        "content": instruction.content,
        "is_active": instruction.is_active,
        "created_at": instruction.created_at.isoformat(),
        "updated_at": instruction.updated_at.isoformat()
    }


@app.post("/api/instructions")
async def create_instruction(payload: InstructionPayload, db: Session = Depends(get_db)):
    service = InstructionService(db)
    instruction = service.create_instruction(
        title=payload.title,
        content=payload.content,
        is_active=payload.is_active
    )
    return {"status": "success", "message": "Instruction created.", "id": instruction.id}


@app.put("/api/instructions/{instruction_id}")
async def update_instruction(instruction_id: int, payload: InstructionUpdatePayload, db: Session = Depends(get_db)):
    service = InstructionService(db)
    instruction = service.update_instruction(
        instruction_id=instruction_id,
        title=payload.title,
        content=payload.content,
        is_active=payload.is_active
    )
    if not instruction:
        raise HTTPException(status_code=404, detail="Instruction not found.")
    return {"status": "success", "message": "Instruction updated."}


@app.delete("/api/instructions/{instruction_id}")
async def delete_instruction(instruction_id: int, db: Session = Depends(get_db)):
    service = InstructionService(db)
    if service.delete_instruction(instruction_id):
        return {"status": "success", "message": "Instruction deleted."}
    raise HTTPException(status_code=404, detail="Instruction not found.")


@app.post("/api/instructions/{instruction_id}/activate")
async def activate_instruction(instruction_id: int, db: Session = Depends(get_db)):
    service = InstructionService(db)
    if service.set_active(instruction_id):
        return {"status": "success", "message": "Instruction activated."}
    raise HTTPException(status_code=404, detail="Instruction not found.")


@app.post("/api/instructions/initialize-default")
async def initialize_default_instruction(db: Session = Depends(get_db)):
    service = InstructionService(db)
    instruction = service.initialize_default_instruction()
    return {"status": "success", "message": "Default instruction initialized.", "id": instruction.id}


# ── Chat Send ───────────────────────────────────────
@app.post("/api/chat/{session_id}/send")
async def handle_chat_send(
    session_id: int,
    payload: ChatSendPayload,
    db: Session = Depends(get_db)
):
    logger.info(f"[SEND] session_id={session_id}")

    chat_manager = ChatService(db)
    
    # Cancel all pending messages in this session
    pending_msgs = db.query(models.ChatMessage).filter(
        models.ChatMessage.session_id == session_id,
        models.ChatMessage.status == "pending"
    ).all()
    for pm in pending_msgs:
        chat_manager.update_message_content(pm.id, "⏹ Cancelled (new request)", status="cancelled")
        logger.info(f"[SEND-CLEANUP] Cancelled pending message {pm.id}")
    
            # فشرده‌سازی هوشمند قبل از ارسال (اگه لازم باشه)
        chat_manager.compress_history_for_context(session_id, max_tokens=800000)

        chat_manager.update_session_title_fallback(session_id, payload.prompt)
    chat_manager.add_message(session_id=session_id, role="user", content=payload.prompt, status="done")

    system_instruction = get_active_instruction_content(db)
    history = chat_manager.get_session_messages(session_id)
    
    messages_payload = [{"role": "system", "content": system_instruction}]
    for msg in history:
        if msg.status == "done" and msg.content:
            messages_payload.append({"role": msg.role, "content": msg.content})

    pending_msg = chat_manager.add_pending_message(session_id=session_id, role="assistant")

    run_llm_in_background(
        message_id=pending_msg.id,
        messages_payload=messages_payload,
        model_name=coder_service.model_name,
        api_key=coder_service.api_key,
        base_url=coder_service.base_url
    )

    return {"status": "processing", "message_id": pending_msg.id}


# ── Code Generation ─────────────────────────────────
@app.post("/api/chat/{session_id}/generate")
async def handle_chat_generation(
    session_id: int,
    request: Request,
    prompt: str = Form(...),
    filename: str = Form(None),
    db: Session = Depends(get_db)
):
    logger.info(f"[INGRESS] Generation request for session_id={session_id}")

    if not prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt is blank.")

    if not filename or not filename.strip():
        logger.info("[AUTO-NAME] Filename omitted. Generating...")
        filename = await coder_service.generate_safe_filename(prompt)
        logger.info(f"[AUTO-NAME] Generated filename: {filename}")

    if not validate_filename(filename):
        raise HTTPException(status_code=400, detail="Invalid filename.")

    if not Path(filename).suffix:
        filename = f"{filename}.py"

    chat_manager = ChatService(db)
    chat_manager.update_session_title_fallback(session_id, prompt)
    chat_manager.add_message(session_id=session_id, role="user", content=prompt)

    system_instruction = get_active_instruction_content(db)

    async def chat_event_generator() -> AsyncGenerator[str, None]:
        accumulated_chunks = []
        try:
            history_messages = chat_manager.get_session_messages(session_id)
            payload_messages = [{"role": "system", "content": system_instruction}]

            for msg in history_messages:
                payload_messages.append({"role": msg.role, "content": msg.content})

            logger.info(f"[OPENROUTER] Streaming for session_id={session_id}")

            response = await coder_service.client.chat.completions.create(
                model=coder_service.model_name,
                messages=payload_messages,
                temperature=0.2,
                max_tokens=16000,
                stream=True
            )

            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    if await request.is_disconnected():
                        logger.warning(f"[ABORT] Client disconnected")
                        return
                    token = chunk.choices[0].delta.content
                    accumulated_chunks.append(token)
                    yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

            full_output = "".join(accumulated_chunks)
            chat_manager.add_message(session_id=session_id, role="assistant", content=full_output)

            safe_path = (TARGET_BASE_DIR / filename).resolve()
            if not str(safe_path).startswith(str(TARGET_BASE_DIR)):
                yield f"data: {json.dumps({'type': 'error', 'detail': 'Path escape error.'})}\n\n"
                return

            os.makedirs(safe_path.parent, exist_ok=True)
            with open(safe_path, "w", encoding="utf-8") as f:
                f.write(full_output)

            yield f"data: {json.dumps({'type': 'final', 'status': 'completed', 'filename': filename})}\n\n"

        except Exception as err:
            logger.error(f"[PIPELINE-FAILURE] Stream error: {str(err)}")
            yield f"data: {json.dumps({'type': 'error', 'detail': 'Pipeline error.'})}\n\n"

    return StreamingResponse(chat_event_generator(), media_type="text/event-stream")


# ── Message Status ──────────────────────────────────
@app.get("/api/message/{message_id}/status")
async def get_message_status(message_id: int, db: Session = Depends(get_db)):
    msg = db.query(models.ChatMessage).filter(models.ChatMessage.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found.")
    return {
        "id": msg.id,
        "status": msg.status,
        "content": msg.content if msg.status in ("done", "error", "cancelled") else None
    }


# ── Stop Generation ─────────────────────────────────
@app.post("/api/message/{message_id}/stop")
async def stop_message_generation(message_id: int, db: Session = Depends(get_db)):
    logger.info(f"[STOP-REQUEST] message_id={message_id}")
    
    with _cancel_lock:
        cancel_event = _cancel_events.get(message_id)
    
    if cancel_event:
        cancel_event.set()
        chat_svc = ChatService(db)
        chat_svc.update_message_content(message_id, "⏹ Stopping...", status="cancelled")
        return {"status": "cancelled"}
    else:
        return {"status": "not_found"}


# ── File Upload ─────────────────────────────────────
UPLOAD_ALLOWED_EXTENSIONS = {'.pdf', '.docx', '.txt', '.pptx', '.xlsx', '.py', '.js', '.html', '.css', '.json', '.md'}
MAX_FILE_SIZE = 50 * 1024 * 1024


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload and extract text from file."""
    logger.info(f"[UPLOAD] Starting upload for file: {file.filename}")
    
    try:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in UPLOAD_ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Unsupported format. Allowed: {', '.join(UPLOAD_ALLOWED_EXTENSIONS)}")
        
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail="File too large (max 50MB)")
        
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        
        text = FileService.extract_text(tmp_path)
        os.unlink(tmp_path)
        
        return {
            "filename": file.filename,
            "text": text,
            "chars": len(text),
            "format": ext
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[UPLOAD] ERROR: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
