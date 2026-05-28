# services/chat_service.py
import logging
from sqlalchemy.orm import Session
from typing import List, Dict, Any
import models
import schemas

logger = logging.getLogger(__name__)

class ChatService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_session(self, title: str = "New Chat Workspace") -> models.ChatSession:
        logger.info("Creating a brand new continuous chat session infrastructure.")
        session_record = models.ChatSession(title=title)
        self.db.add(session_record)
        self.db.commit()
        self.db.refresh(session_record)
        return session_record

    def get_recent_sessions(self, limit: int = 25) -> List[models.ChatSession]:
        return self.db.query(models.ChatSession).order_by(
            models.ChatSession.updated_at.desc()
        ).limit(limit).all()

    def get_session_messages(self, session_id: int) -> List[models.ChatMessage]:
        return self.db.query(models.ChatMessage).filter(
            models.ChatMessage.session_id == session_id
        ).order_by(models.ChatMessage.created_at.asc()).all()

    def add_message(self, session_id: int, role: str, content: str) -> models.ChatMessage:
        logger.info(f"Appending new structural interaction message context log for role: {role}")
        message_record = models.ChatMessage(
            session_id=session_id,
            role=role,
            content=content
        )
        self.db.add(message_record)
        
        # Touch the session to update its updated_at column for history sorting
        session_record = self.db.query(models.ChatSession).filter(models.ChatSession.id == session_id).first()
        if session_record:
            session_record.updated_at = models.datetime.utcnow()
            
        self.db.commit()
        self.db.refresh(message_record)
        return message_record

    def update_session_title_fallback(self, session_id: int, initial_prompt: str) -> None:
        session_record = self.db.query(models.ChatSession).filter(models.ChatSession.id == session_id).first()
        if session_record and (session_record.title == "New Chat Workspace" or not session_record.title):
            # Compute slick dynamic title from initial contextual user input token boundaries
            computed_title = initial_prompt[:40] + "..." if len(initial_prompt) > 40 else initial_prompt
            session_record.title = computed_title
            self.db.commit()

    def compile_openrouter_payload(self, session_messages: List[models.ChatMessage]) -> List[Dict[str, str]]:
        payload = []
        for msg in session_messages:
            payload.append({"role": msg.role, "content": msg.content})
        return payload

    def rename_session(self, session_id: int, new_title: str) -> bool:
        """Updates the title of a specific chat session."""
        session = self.db.query(models.ChatSession).filter(models.ChatSession.id == session_id).first()
        if session:
            session.title = new_title
            self.db.commit()
            return True
        return False

    def delete_session(self, session_id: int) -> bool:
        """Deletes a chat session and cascades cleanup to associated messages."""
        session = self.db.query(models.ChatSession).filter(models.ChatSession.id == session_id).first()
        if session:
            self.db.delete(session)
            self.db.commit()
            return True
        return False