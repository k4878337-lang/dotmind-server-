from datetime import datetime
from typing import Optional
from pydantic import BaseModel

class AgentProfileUpdate(BaseModel):
    name: Optional[str] = None
    personality: Optional[str] = None
    instructions: Optional[str] = None
    avatar_color: Optional[str] = None

class AgentProfileOut(BaseModel):
    id: str
    user_id: str
    name: str
    personality: str
    instructions: str
    avatar_color: str
    created_at: datetime

    class Config:
        orm_mode = True
