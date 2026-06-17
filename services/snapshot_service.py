# services/snapshot_service.py

import os
import re
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Snapshot Storage ───────────────────────────────
SNAPSHOTS_DIR = Path("snapshots").resolve()
SNAPSHOTS_DIR.mkdir(exist_ok=True)

# ── Snapshot Prompt Template ────────────────────────
SNAPSHOT_PROMPT = """You are about to lose all chat history. Write a comprehensive project snapshot.

⚠️ IMPORTANT RULES:
- ONLY include information about the MAIN PROJECT we're working on.
- IGNORE casual conversations, personal questions, resume editing, greetings, or unrelated side topics.
- IGNORE any code or files that are NOT part of the main project.
- IGNORE debugging sessions, error fixes, and trial-and-error unless they resulted in a permanent architectural change.
- FOCUS ONLY on: project purpose, architecture, current state, active files, pending tasks, and key decisions.

Include these sections:

1. **Project Overview**: What is the main project? What does it do? What tech stack?
2. **Architecture**: Key modules, folder structure, important files and their purpose
3. **Current State**: What's completed? What features are working?
4. **Active Files**: List only the core project files with a brief description
5. **Pending Tasks**: What needs to be done next?
6. **Key Decisions**: Important design choices we made (only permanent ones)
7. **Quick Reference**: Any commands, credentials structure, or patterns we use frequently

Write as a concise technical document. Keep it clean and focused.
Use English for technical terms."""


class SnapshotService:
    """Service for creating and managing chat snapshots."""
    
    def __init__(self, db_session):
        self.db = db_session
    
    def get_snapshot_prompt(self) -> str:
        """Get the hidden prompt for snapshot generation."""
        return SNAPSHOT_PROMPT
    
    def save_snapshot_to_file(
        self, 
        session_id: int, 
        session_title: str, 
        snapshot_content: str
    ) -> str:
        """
        Save snapshot content to a text file.
        Returns the file path.
        """
        # Clean filename
        safe_title = re.sub(r'[^\w\s-]', '', session_title or 'untitled')
        safe_title = safe_title[:50].strip().replace(' ', '_')
        
        now = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"snapshot_{session_id}_{now}_{safe_title}.txt"
        filepath = SNAPSHOTS_DIR / filename
        
        # Build full content
        header = f"""{'='*70}
📸 PROJECT SNAPSHOT
{'='*70}
Session ID   : {session_id}
Session Title: {session_title or 'Untitled'}
Created At   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
{'='*70}

"""
        
        footer = f"""

{'='*70}
📝 END OF SNAPSHOT
{'='*70}

آمادهٔ دریافت کدهای پروژه هستم. لطفاً فایل‌ها رو آپلود کنید.
"""
        
        full_content = header + snapshot_content + footer
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(full_content)
        
        logger.info(f"[SNAPSHOT] Saved to: {filepath}")
        return str(filepath)
    
    def get_all_snapshots(self, session_id: Optional[int] = None) -> list:
        """Get all snapshot files, optionally filtered by session_id."""
        snapshots = []
        
        if not SNAPSHOTS_DIR.exists():
            return snapshots
        
        for filepath in sorted(SNAPSHOTS_DIR.glob("snapshot_*.txt"), reverse=True):
            # Parse filename: snapshot_{session_id}_{timestamp}_{title}.txt
            name = filepath.stem  # without .txt
            parts = name.split('_', 3)  # ['snapshot', 'id', 'timestamp', 'title']
            
            if len(parts) < 3:
                continue
            
            try:
                file_session_id = int(parts[1])
            except ValueError:
                continue
            
            if session_id and file_session_id != session_id:
                continue
            
            # Get file info
            stat = filepath.stat()
            size_kb = round(stat.st_size / 1024, 1)
            
            # Read first line for preview
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    first_lines = f.read(200)
            except:
                first_lines = ""
            
            snapshots.append({
                "filename": filepath.name,
                "filepath": str(filepath),
                "session_id": file_session_id,
                "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "size_kb": size_kb,
                "preview": first_lines[:150] + "..." if len(first_lines) > 150 else first_lines
            })
        
        return snapshots
    
    def read_snapshot(self, filepath: str) -> str:
        """Read snapshot file content."""
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Snapshot not found: {filepath}")
        
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    
    def delete_snapshot(self, filepath: str) -> bool:
        """Delete a snapshot file."""
        path = Path(filepath)
        if path.exists():
            path.unlink()
            logger.info(f"[SNAPSHOT] Deleted: {filepath}")
            return True
        return False
    
    def clear_session_messages(self, session_id: int) -> int:
        """
        Delete all messages for a session from database.
        Returns number of deleted messages.
        """
        from models import ChatMessage
        
        messages = self.db.query(ChatMessage).filter(
            ChatMessage.session_id == session_id
        ).all()
        
        count = len(messages)
        for msg in messages:
            self.db.delete(msg)
        
        self.db.commit()
        logger.info(f"[SNAPSHOT] Cleared {count} messages for session {session_id}")
        return count
