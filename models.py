# models.py
from sqlalchemy import Column, Integer, String, Text, DateTime
from datetime import datetime
from database import Base

class GenerationHistory(Base):
    __tablename__ = "generation_history"

    id = Column(Integer, primary_key=True, index=True)
    prompt = Column(String(500), nullable=False)
    generated_code = Column(Text, nullable=False)
    filename = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
