# main.py
import os
import json
import logging
from fastapi import BackgroundTasks
from sqlalchemy.orm import Session as DBSession
from database import SessionLocal
from pathlib import Path
from typing import AsyncGenerator
from fastapi import FastAPI, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from decouple import config
from pydantic import BaseModel, Field

import models
from database import engine, get_db
from services.openrouter_service import OpenRouterCodingService
from services.chat_service import ChatService

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
ALLOWED_EXTENSIONS = {'.py', '.js', '.ts', '.java', '.cpp', '.c', '.h', '.cs', '.go', '.rs', '.html', '.css', '.txt'}
TARGET_BASE_DIR = Path("generated_components").resolve()


class ChatRenamePayload(BaseModel):
    title: str = Field(..., min_length=1, max_length=128)


class ChatSendPayload(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=100000)


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
    raise HTTPException(status_code=404, detail="Target tracking thread context missing.")


@app.post("/api/chat/{session_id}/delete")
async def delete_chat_session(session_id: int, db: Session = Depends(get_db)):
    chat_manager = ChatService(db)
    if chat_manager.delete_session(session_id):
        return {"status": "success", "message": "Session successfully cleared from DB stack."}
    raise HTTPException(status_code=404, detail="Target tracking thread context missing.")


def run_llm_in_background(message_id: int, messages_payload: list, model_name: str, api_key: str, base_url: str) -> None:
    """Runs synchronously in a thread — completely decoupled from the HTTP request lifecycle."""
    import asyncio
    from openai import AsyncOpenAI

    async def _call():
        db: DBSession = SessionLocal()
        try:
            client = AsyncOpenAI(
                base_url=base_url,
                api_key=api_key,
                default_headers={"HTTP-Referer": "https://localhost:8000"}
            )
            response = await client.chat.completions.create(
                model=model_name,
                messages=messages_payload,
                temperature=0.3,
                max_tokens=8000,
                stream=False
            )
            reply = response.choices[0].message.content.strip()
            chat_svc = ChatService(db)
            chat_svc.update_message_content(message_id, reply, status="done")
            logger.info(f"[BG-TASK] Message {message_id} completed successfully.")
        except Exception as e:
            logger.error(f"[BG-TASK-ERROR] Message {message_id} failed: {str(e)}")
            chat_svc = ChatService(db)
            chat_svc.update_message_content(message_id, f"⚠️ Error: {str(e)}", status="error")
        finally:
            db.close()

    asyncio.run(_call())


@app.post("/api/chat/{session_id}/send")
async def handle_chat_send(
    session_id: int,
    payload: ChatSendPayload,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    logger.info(f"[SEND] session_id={session_id}")

    chat_manager = ChatService(db)
    chat_manager.update_session_title_fallback(session_id, payload.prompt)
    chat_manager.add_message(session_id=session_id, role="user", content=payload.prompt, status="done")

    # Build history BEFORE creating pending message
    history = chat_manager.get_session_messages(session_id)
    system_instruction = (
        "You are OWL, a Senior Python/AI Engineer and coding assistant. "
        "Answer clearly and helpfully. Use markdown for code blocks."
    )
    messages_payload = [{"role": "system", "content": system_instruction}]
    for msg in history:
        if msg.status == "done" and msg.content:
            messages_payload.append({"role": msg.role, "content": msg.content})

    # Create placeholder — frontend polls this ID
    pending_msg = chat_manager.add_pending_message(session_id=session_id, role="assistant")

    background_tasks.add_task(
        run_llm_in_background,
        message_id=pending_msg.id,
        messages_payload=messages_payload,
        model_name=coder_service.model_name,
        api_key=coder_service.api_key,
        base_url=coder_service.base_url
    )

    return {"status": "processing", "message_id": pending_msg.id}


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
        raise HTTPException(status_code=400, detail="Required user interaction prompt is blank.")

    if not filename or not filename.strip():
        logger.info("[AUTO-NAME] Filename omitted. Launching predictive extraction sub-pipeline.")
        filename = await coder_service.generate_safe_filename(prompt)
        logger.info(f"[AUTO-NAME] LLM designated filename: {filename}")

    if not validate_filename(filename):
        raise HTTPException(status_code=400, detail="Sandbox structure constraint extension violation.")

    if not Path(filename).suffix:
        filename = f"{filename}.py"

    chat_manager = ChatService(db)
    chat_manager.update_session_title_fallback(session_id, prompt)
    chat_manager.add_message(session_id=session_id, role="user", content=prompt)

    async def chat_event_generator() -> AsyncGenerator[str, None]:
        accumulated_chunks = []
        try:
            history_messages = chat_manager.get_session_messages(session_id)
            payload_messages = []

            system_instruction = (
                "You are OWL, a Senior Python/AI Engineer. Output clean, robust, OOP-compliant code "
                "with strict type hints. Do NOT include markdown blocks like ```python or ```, "
                "do NOT include conversational explanations or prose text. Output ONLY valid, raw executable code."
            )
            payload_messages.append({"role": "system", "content": system_instruction})

            for msg in history_messages:
                payload_messages.append({"role": msg.role, "content": msg.content})

            logger.info(f"[OPENROUTER] Streaming for session_id={session_id}, messages={len(payload_messages)}")

            response = await coder_service.client.chat.completions.create(
                model=coder_service.model_name,
                messages=payload_messages,
                temperature=0.2,
                max_tokens=4000,
                stream=True
            )

            async def parse_stream():
                async for chunk in response:
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content

            async def token_stream():
                async for token in parse_stream():
                    if await request.is_disconnected():
                        logger.warning(f"[ABORT] Client disconnected for session_id={session_id}")
                        return
                    accumulated_chunks.append(token)
                    yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

            async for stream_frame in token_stream():
                yield stream_frame

            full_generated_output = "".join(accumulated_chunks)
            chat_manager.add_message(session_id=session_id, role="assistant", content=full_generated_output)

            safe_target_path = (TARGET_BASE_DIR / filename).resolve()
            if not str(safe_target_path).startswith(str(TARGET_BASE_DIR)):
                yield f"data: {json.dumps({'type': 'error', 'detail': 'Sandbox path escape containment failure.'})}\n\n"
                return

            os.makedirs(safe_target_path.parent, exist_ok=True)
            with open(safe_target_path, "w", encoding="utf-8") as file_handle:
                file_handle.write(full_generated_output)

            yield f"data: {json.dumps({'type': 'final', 'status': 'completed', 'filename': filename})}\n\n"

        except Exception as err:
            logger.error(f"[PIPELINE-FAILURE] Stream error: {str(err)}")
            yield f"data: {json.dumps({'type': 'error', 'detail': 'Internal pipeline operational error.'})}\n\n"

    return StreamingResponse(chat_event_generator(), media_type="text/event-stream")

@app.get("/api/message/{message_id}/status")
async def get_message_status(message_id: int, db: Session = Depends(get_db)):
    """Frontend polls this every 2s to check if background LLM task is done."""
    from models import ChatMessage
    msg = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found.")
    return {
        "id": msg.id,
        "status": msg.status,
        "content": msg.content if msg.status in ("done", "error") else None
    }