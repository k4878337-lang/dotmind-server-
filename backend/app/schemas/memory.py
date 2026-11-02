from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, validator

class MemoryCreate(BaseModel):
    content: str
    category: Optional[str] = "preference"  # preference, project_note, decision, fact
    importance: Optional[int] = 3
    source_conversation_id: Optional[str] = None

    @validator("importance")
    def validate_importance(cls, v):
        if v is not None and (v < 1 or v > 5):
            raise ValueError("Importance must be between 1 and 5")
        return v

    @validator("content")
    def validate_content(cls, v):
        if not v or not v.strip():
            raise ValueError("Memory content cannot be empty")
        return v.strip()

class MemoryUpdate(BaseModel):
    content: Optional[str] = None
    category: Optional[str] = None
    importance: Optional[int] = None
    is_active: Optional[bool] = None

    @validator("importance")
    def validate_importance(cls, v):
        if v is not None and (v < 1 or v > 5):
            raise ValueError("Importance must be between 1 and 5")
        return v

class MemoryOut(BaseModel):
    id: str
    user_id: str
    category: str
    content: str
    importance: int
    is_active: bool
    source_conversation_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

class MemorySearchQuery(BaseModel):
    query: str
    category: Optional[str] = None
    limit: Optional[int] = 5
