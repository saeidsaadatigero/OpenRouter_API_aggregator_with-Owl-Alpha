# main.py
import json
import logging
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

import models
from database import engine, Base, get_db
from services.openrouter_service import OpenRouterCodingService

# Configure logging pipeline
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("INGRESS")

# Initialize database schemas
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Agentic Code Studio Engine")

# Mount system asset paths
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Initialize isolated workspace sandbox
TARGET_BASE_DIR = Path("./generated_components").resolve()
TARGET_BASE_DIR.mkdir(exist_ok=True)

coding_service = OpenRouterCodingService()


def sanitize_and_validate_path(filename: str) -> Path:
    """Enforces strict structural boundary locks to mitigate path traversal exploits."""
    normalized_path = Path(filename).name
    safe_target_path = (TARGET_BASE_DIR / normalized_path).resolve()
    return safe_target_path


# main.py
@app.get("/", response_class=HTMLResponse)
async def render_dashboard(request: Request, db: Session = Depends(get_db)):
    """Fetches full analytical execution records to populate the Recents sidebar matrix."""
    sessions = (
        db.query(models.ChatSession)
        .order_by(models.ChatSession.updated_at.desc())
        .all()
    )
    # Explicitly pass request as a separate keyword argument to align with modern Starlette specifications
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"history": sessions}
    )

@app.get("/api/sessions/{session_id}")
async def get_session_thread(session_id: int, db: Session = Depends(get_db)):
    """Pulls precise historical chat frames linked to a specific session context vector."""
    session_node = db.query(models.ChatSession).filter(models.ChatSession.id == session_id).first()
    if not session_node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Requested chat session thread allocation not found."
        )
    
    # Extract the last compiled code payload from the assistant's message history
    last_code = ""
    for message in reversed(session_node.messages):
        if message.role == "assistant" and message.generated_code:
            last_code = message.generated_code
            break

    return {
        "id": session_node.id,
        "title": session_node.title,
        "last_compiled_code": last_code
    }


@app.post("/api/generate")
async def generate_code_pipeline(
    request: Request,
    filename: str = Form(...),
    prompt: str = Form(...),
    session_id: str = Form(None),
    db: Session = Depends(get_db)
):
    """Intercepts compilation requests and handles stateful multiplex SSE token streaming."""
    logger.info(f"[INGRESS] Processing generation execution thread for asset: {filename}")
    
    # Path sandbox check
    try:
        validated_file_path = sanitize_and_validate_path(filename)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Security execution sandbox out-of-bounds boundary breach."
        )

    # Establish or fetch operational Session Node
    if session_id and session_id.strip():
        current_session = db.query(models.ChatSession).filter(models.ChatSession.id == int(session_id)).first()
        if not current_session:
            current_session = models.ChatSession(title=f"Refactor: {filename}")
            db.add(current_session)
            db.commit()
            db.refresh(current_session)
    else:
        current_session = models.ChatSession(title=f"Feature: {filename}")
        db.add(current_session)
        db.commit()
        db.refresh(current_session)

    # Commit historical User prompt message payload frame
    user_message = models.ChatMessage(
        session_id=current_session.id,
        role="user",
        content=prompt,
        filename=filename
    )
    db.add(user_message)
    db.commit()

    # Extract historical message context array for LLM memory buffer assembly
    past_messages = (
        db.query(models.ChatMessage)
        .filter(models.ChatMessage.session_id == current_session.id)
        .order_by(models.ChatMessage.created_at.asc())
        .all()
    )
    history_payload = [{"role": m.role, "content": m.content} for m in past_messages[:-1]]

    async def event_generator():
        accumulated_response_buffer = ""
        try:
            async for token in coding_service.generate_conversational_stream(history_payload, prompt):
                if await request.is_disconnected():
                    logger.warning("[CIRCUIT-BREAKER] Client disconnected mid-stream. Terminating upstream socket.")
                    break
                accumulated_response_buffer += token
                yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

            # Strict IO Safe Flush directly to absolute workspace storage node
            with open(validated_file_path, "w", encoding="utf-8") as target_file:
                target_file.write(accumulated_response_buffer)
            logger.info(f"[IO-WRITE] Flushed memory buffer pipeline to disk safely: {validated_file_path}")

            # Commit historical Assistant message response payload frame to relational storage
            assistant_message = models.ChatMessage(
                session_id=current_session.id,
                role="assistant",
                content=f"Code compiled successfully for component {filename}.",
                filename=filename,
                generated_code=accumulated_response_buffer
            )
            db.add(assistant_message)
            
            # Touch session timestamp update execution state
            current_session.title = f"Refactor: {filename}"
            db.commit()
            logger.info(f"[DATABASE-TX] Committed multi-turn generation audit logs. Index node ID: {current_session.id}")

            yield f"data: {json.dumps({'type': 'final', 'session_id': current_session.id})}\n\n"

        except Exception as err:
            logger.error(f"[PIPELINE-FAILURE] Stream broken down due to runtime root anomaly: {str(err)}")
            yield f"data: {json.dumps({'type': 'error', 'detail': 'Internal pipeline operational error.'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")