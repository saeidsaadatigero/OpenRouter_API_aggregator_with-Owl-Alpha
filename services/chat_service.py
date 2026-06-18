# services/chat_service.py

import logging
import re
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from datetime import datetime
import models

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

    def add_message(self, session_id: int, role: str, content: str, status: str = "done") -> models.ChatMessage:
        message_record = models.ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            status=status
        )
        self.db.add(message_record)
        
        session_record = self.db.query(models.ChatSession).filter(models.ChatSession.id == session_id).first()
        if session_record:
            from datetime import datetime
            session_record.updated_at = datetime.utcnow()
            
        self.db.commit()
        self.db.refresh(message_record)
        return message_record

    def update_session_title_fallback(self, session_id: int, initial_prompt: str) -> None:
        session_record = self.db.query(models.ChatSession).filter(models.ChatSession.id == session_id).first()
        if session_record and (session_record.title == "New Chat Workspace" or not session_record.title):
            computed_title = initial_prompt[:40] + "..." if len(initial_prompt) > 40 else initial_prompt
            session_record.title = computed_title
            self.db.commit()

    def rename_session(self, session_id: int, new_title: str) -> bool:
        session = self.db.query(models.ChatSession).filter(models.ChatSession.id == session_id).first()
        if session:
            session.title = new_title
            self.db.commit()
            return True
        return False

    def delete_session(self, session_id: int) -> bool:
        session = self.db.query(models.ChatSession).filter(models.ChatSession.id == session_id).first()
        if session:
            self.db.delete(session)
            self.db.commit()
            return True
        return False
    
    def add_pending_message(self, session_id: int, role: str) -> models.ChatMessage:
        msg = models.ChatMessage(
            session_id=session_id,
            role=role,
            content="",
            status="pending"
        )
        self.db.add(msg)
        self.db.commit()
        self.db.refresh(msg)
        return msg

    def update_message_content(self, message_id: int, content: str, status: str = "done") -> None:
        msg = self.db.query(models.ChatMessage).filter(models.ChatMessage.id == message_id).first()
        if msg:
            msg.content = content
            msg.status = status
            self.db.commit()

    # ═══════════════════════════════════════════════════════
    # ── History Compression ─────────────────────────────
    # ═══════════════════════════════════════════════════════

    def compress_history_for_context(self, session_id: int, max_tokens: int = 800000) -> None:
        """
        Smart compression: trim old messages if total tokens exceed max_tokens.
        Keeps recent messages intact, trims older long responses.
        """
        messages = self.get_session_messages(session_id)
        
        if not messages:
            return
        
        total_chars = sum(len(m.content or "") for m in messages)
        total_tokens = total_chars // 4
        
        if total_tokens <= max_tokens:
            logger.info(f"[COMPRESS] Session {session_id}: {total_tokens} tokens (no compression needed)")
            return
        
        logger.info(f"[COMPRESS] Session {session_id}: {total_tokens} tokens > {max_tokens} limit, compressing...")
        
        # Keep last 10 messages intact, compress older ones
        KEEP_LAST = 10
        
        if len(messages) <= KEEP_LAST:
            return
        
        messages_to_compress = messages[:-KEEP_LAST]
        compressed_count = 0
        
        for msg in messages_to_compress:
            if msg.role == "assistant" and msg.content and len(msg.content) > 500:
                original_len = len(msg.content)
                # Keep first 200 chars + last 100 chars
                msg.content = msg.content[:200] + "\n\n[... trimmed for context ...]\n\n" + msg.content[-100:]
                compressed_count += 1
        
        self.db.commit()
        
        new_total = sum(len(m.content or "") for m in self.get_session_messages(session_id))
        new_tokens = new_total // 4
        
        logger.info(f"[COMPRESS] Compressed {compressed_count} messages. Tokens: {total_tokens} -> {new_tokens}")

    def aggressive_compress(self, session_id: int) -> int:
        """
        Aggressive compression:
        - Keep all code blocks intact
        - Keep first 100 chars + last 50 chars of each message
        - Delete all old messages, create one summary message
        - Returns: new total character count
        """
        messages = self.get_session_messages(session_id)
        
        if len(messages) == 0:
            return 0
        
        logger.info(f"[AGGRESSIVE-COMPRESS] session_id={session_id} messages={len(messages)}")
        
        parts = []
        
        for msg in messages:
            content = msg.content or ''
            role = msg.role
            
            # Extract all code blocks
            codes = re.findall(r'```[\s\S]*?```', content)
            
            if codes:
                # Keep codes + first 100 chars of text
                text_no_code = re.sub(r'```[\s\S]*?```', '', content).strip()
                short_text = text_no_code[:100] if text_no_code else ""
                parts.append(f"[{role}] {short_text}\n" + "\n".join(codes))
            else:
                # No code: keep first 150 chars
                short = content[:150].replace('\n', ' ')
                parts.append(f"[{role}] {short}...")
        
        compressed = "📦 **COMPRESSED (codes kept, text trimmed):**\n\n" + "\n\n---\n\n".join(parts)
        
        # Delete all old messages
        for msg in messages:
            self.db.delete(msg)
        
        # Add compressed summary as assistant message (not system)
        new_msg = models.ChatMessage(
            session_id=session_id,
            role="assistant",  # Changed from "system" to "assistant"
            content=compressed,
            status="done"
        )
        self.db.add(new_msg)
        self.db.commit()
        
        logger.info(f"[AGGRESSIVE-COMPRESS] Done: {len(messages)} msgs → {len(compressed)} chars")
        return len(compressed)

    def get_session_token_count(self, session_id: int) -> dict:
        """
        Calculate token usage for a session.
        Returns dict with: total_chars, total_tokens, percentage, message_count
        """
        messages = self.get_session_messages(session_id)
        
        total_chars = 0
        message_count = 0
        
        for msg in messages:
            if msg.content and msg.status in ("done", "pending"):
                total_chars += len(msg.content)
                message_count += 1
        
        # Simple estimation: 1 token ≈ 4 chars
        total_tokens = total_chars // 4
        
        # Context window (1M tokens for owl-alpha)
        MAX_CONTEXT_TOKENS = 1_048_576
        percentage = min(round((total_tokens / MAX_CONTEXT_TOKENS) * 100, 1), 100)
        
        return {
            "session_id": session_id,
            "total_chars": total_chars,
            "total_tokens": total_tokens,
            "max_tokens": MAX_CONTEXT_TOKENS,
            "percentage": percentage,
            "message_count": message_count,
            "warning_level": self._get_warning_level(percentage)
        }

    @staticmethod
    def _get_warning_level(percentage: float) -> str:
        """Determine warning level based on context usage percentage."""
        if percentage >= 100:
            return "blocked"
        elif percentage >= 95:
            return "critical"
        elif percentage >= 90:
            return "warning"
        elif percentage >= 85:
            return "notice"
        else:
            return "ok"

    def get_token_bar(self, session_id: int, bar_length: int = 10) -> str:
        """
        Generate a visual progress bar string.
        Example: "████████░░ 85%"
        """
        info = self.get_session_token_count(session_id)
        percentage = info["percentage"]
        
        filled = int(bar_length * percentage / 100)
        empty = bar_length - filled
        
        bar = "█" * filled + "░" * empty
        
        # Format tokens for display
        total_k = info["total_tokens"] // 1000
        max_k = info["max_tokens"] // 1000
        
        return f"Context: {bar} {percentage}% | {total_k}K / {max_k}K"

    def get_session(self, session_id: int):
        """Get a session by ID."""
        return self.db.query(models.ChatSession).filter(
            models.ChatSession.id == session_id
        ).first()
