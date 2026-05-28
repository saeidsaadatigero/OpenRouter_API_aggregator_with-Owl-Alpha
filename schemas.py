# schemas.py
from pydantic import BaseModel
from datetime import datetime

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
