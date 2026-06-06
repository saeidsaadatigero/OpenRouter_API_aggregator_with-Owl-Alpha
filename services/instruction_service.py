# services/instruction_service.py
import logging
from sqlalchemy.orm import Session
from typing import List, Optional
import models

logger = logging.getLogger(__name__)


class InstructionService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_active_instruction(self) -> Optional[models.SystemInstruction]:
        return self.db.query(models.SystemInstruction).filter(
            models.SystemInstruction.is_active == True
        ).first()

    def get_all_instructions(self) -> List[models.SystemInstruction]:
        return self.db.query(models.SystemInstruction).order_by(
            models.SystemInstruction.updated_at.desc()
        ).all()

    def get_instruction_by_id(self, instruction_id: int) -> Optional[models.SystemInstruction]:
        return self.db.query(models.SystemInstruction).filter(
            models.SystemInstruction.id == instruction_id
        ).first()

    def create_instruction(self, title: str, content: str, is_active: bool = True) -> models.SystemInstruction:
        if is_active:
            self._deactivate_all()
        
        instruction = models.SystemInstruction(
            title=title,
            content=content,
            is_active=is_active
        )
        self.db.add(instruction)
        self.db.commit()
        self.db.refresh(instruction)
        logger.info(f"[INSTRUCTION] Created new instruction: {title}")
        return instruction

    def update_instruction(self, instruction_id: int, title: str = None, content: str = None, is_active: bool = None) -> Optional[models.SystemInstruction]:
        instruction = self.get_instruction_by_id(instruction_id)
        if not instruction:
            return None

        if title is not None:
            instruction.title = title
        if content is not None:
            instruction.content = content
        if is_active is not None:
            if is_active:
                self._deactivate_all()
            instruction.is_active = is_active

        self.db.commit()
        self.db.refresh(instruction)
        logger.info(f"[INSTRUCTION] Updated instruction: {instruction.title}")
        return instruction

    def delete_instruction(self, instruction_id: int) -> bool:
        instruction = self.get_instruction_by_id(instruction_id)
        if instruction:
            self.db.delete(instruction)
            self.db.commit()
            logger.info(f"[INSTRUCTION] Deleted instruction ID: {instruction_id}")
            return True
        return False

    def set_active(self, instruction_id: int) -> bool:
        instruction = self.get_instruction_by_id(instruction_id)
        if instruction:
            self._deactivate_all()
            instruction.is_active = True
            self.db.commit()
            logger.info(f"[INSTRUCTION] Set active: {instruction.title}")
            return True
        return False

    def _deactivate_all(self) -> None:
        self.db.query(models.SystemInstruction).update({models.SystemInstruction.is_active: False})
        self.db.commit()

    def get_default_instruction_content(self) -> str:
        return """
You are my Senior Engineering Partner.
Your Behavior:
- You write clean, production-ready code.
- You think in systems and architecture, not just isolated functions.
- You are not a generic tutorial bot; you act as a real technical co-founder.
"""

    def initialize_default_instruction(self) -> models.SystemInstruction:
        existing = self.get_active_instruction()
        if not existing:
            default_content = self.get_default_instruction_content()
            return self.create_instruction(
                title="Default OWL Instructions",
                content=default_content,
                is_active=True
            )
        return existing