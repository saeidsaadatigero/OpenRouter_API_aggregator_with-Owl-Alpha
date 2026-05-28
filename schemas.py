# schemas.py
from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional

class MessageCreate(BaseModel):
    role: str
    content: str

class MessageResponse(BaseModel):
    id: int
    session_id: int
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True

class SessionCreate(BaseModel):
    title: Optional[str] = "New Chat Workspace"

class SessionResponse(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    messages: List[MessageResponse] = []

    class Config:
        from_attributes = True

class CodeRequest(BaseModel):
    prompt: str
    filename: str

class HistoryResponse(BaseModel):
    id: int
    prompt: str
    generated_code: str
    filename: str
    created_at: datetime

    class Config:
        from_attributes = True