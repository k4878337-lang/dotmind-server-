from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel

class ConversationCreate(BaseModel):
    title: Optional[str] = "New Conversation"

class ConversationOut(BaseModel):
    id: str
    user_id: str
    title: str
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

class AttachmentPayload(BaseModel):
    id: Optional[str] = None
    filename: str
    mime_type: str
    size_bytes: int = 0
    file_url: Optional[str] = None
    base64_data: Optional[str] = None

class AttachmentUploadRequest(BaseModel):
    filename: str
    mime_type: str
    base64_data: str

class AttachmentUploadResponse(BaseModel):
    id: str
    filename: str
    mime_type: str
    size_bytes: int
    file_url: str
    base64_data: Optional[str] = None

class MessageCreate(BaseModel):
    content: str
    attachments: Optional[List[AttachmentPayload]] = []

class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    tool_calls: Optional[str] = None
    attachments: Optional[str] = None
    status: str
    created_at: datetime

    class Config:
        orm_mode = True

class ConversationDetail(ConversationOut):
    messages: List[MessageOut] = []
