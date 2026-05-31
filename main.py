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
from services.instruction_service import InstructionService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

models.Base.metadata.create_all(bind=engine)

# Initialize default instruction on startup
db_init = SessionLocal()
try:
    instruction_service_init = InstructionService(db_init)
    instruction_service_init.initialize_default_instruction()
finally:
    db_init.close()

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


class InstructionPayload(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)
    is_active: bool = Field(default=True)


class InstructionUpdatePayload(BaseModel):
    title: str = Field(default=None, min_length=1, max_length=255)
    content: str = Field(default=None, min_length=1)
    is_active: bool = Field(default=None)


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


@app.get("/api/config")
async def get_config():
    """Get frontend configuration."""
    return {
        "max_prompt_length": MAX_PROMPT_LENGTH,
        "max_chars": config("MAX_CHARS", default=100000, cast=int)
    }


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
    return {
        "status": "success",
        "message": "Instruction created successfully.",
        "id": instruction.id
    }


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
    return {
        "status": "success",
        "message": "Instruction updated successfully."
    }


@app.delete("/api/instructions/{instruction_id}")
async def delete_instruction(instruction_id: int, db: Session = Depends(get_db)):
    service = InstructionService(db)
    if service.delete_instruction(instruction_id):
        return {"status": "success", "message": "Instruction deleted successfully."}
    raise HTTPException(status_code=404, detail="Instruction not found.")


@app.post("/api/instructions/{instruction_id}/activate")
async def activate_instruction(instruction_id: int, db: Session = Depends(get_db)):
    service = InstructionService(db)
    if service.set_active(instruction_id):
        return {"status": "success", "message": "Instruction activated successfully."}
    raise HTTPException(status_code=404, detail="Instruction not found.")


@app.post("/api/instructions/initialize-default")
async def initialize_default_instruction(db: Session = Depends(get_db)):
    service = InstructionService(db)
    instruction = service.initialize_default_instruction()
    return {
        "status": "success",
        "message": "Default instruction initialized.",
        "id": instruction.id
    }


def run_llm_in_background(message_id: int, messages_payload: list, model_name: str, api_key: str, base_url: str) -> None:
    """Runs synchronously in a thread — completely decoupled from the HTTP request lifecycle."""
    import asyncio
    from openai import AsyncOpenAI

    async def _call():
        db: DBSession = SessionLocal()
        client = None
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
                max_tokens=16000,  # برای پاسخ‌های طولانی
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
            if client:
                try:
                    await client.close()
                except:
                    pass
            db.close()

    try:
        asyncio.run(_call())
    except RuntimeError:
        # Event loop is closed, create a new one
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_call())
        finally:
            loop.close()


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

    # Get active system instruction
    system_instruction = get_active_instruction_content(db)
    
    # Build history BEFORE creating pending message
    history = chat_manager.get_session_messages(session_id)
    
    messages_payload = [{"role": "system", "content": system_instruction}]
    for msg in history:
        if msg.status == "done" and msg.content:
            messages_payload.append({"role": msg.role, "content": msg.content})

    # Create placeholder
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

    # Get active system instruction
    system_instruction = get_active_instruction_content(db)

    async def chat_event_generator() -> AsyncGenerator[str, None]:
        accumulated_chunks = []
        try:
            history_messages = chat_manager.get_session_messages(session_id)
            payload_messages = []

            payload_messages.append({"role": "system", "content": system_instruction})

            for msg in history_messages:
                payload_messages.append({"role": msg.role, "content": msg.content})

            logger.info(f"[OPENROUTER] Streaming for session_id={session_id}, messages={len(payload_messages)}")

            response = await coder_service.client.chat.completions.create(
                model=coder_service.model_name,
                messages=payload_messages,
                temperature=0.2,
                max_tokens=16000,  # برای پاسخ‌های طولانی
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
