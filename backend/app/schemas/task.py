from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field

class TaskStepCreate(BaseModel):
    name: str
    description: str
    tool_name: Optional[str] = None
    tool_args: Optional[str] = None
    requires_approval: bool = False

class TaskCreate(BaseModel):
    title: Optional[str] = Field(None, description="Short task title (auto-generated if omitted)")
    goal: str = Field(..., min_length=3, description="High-level user goal")
    priority: Optional[int] = Field(3, ge=1, le=5, description="1 (low) to 5 (critical)")
    custom_steps: Optional[List[TaskStepCreate]] = Field(None, description="Optional pre-defined steps")

class TaskStepOut(BaseModel):
    id: str
    task_id: str
    step_order: int
    name: str
    description: str
    tool_name: Optional[str] = None
    tool_args: Optional[str] = None
    status: str
    requires_approval: bool
    approval_status: str
    approval_comment: Optional[str] = None
    result: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

class TaskLogOut(BaseModel):
    id: str
    task_id: str
    step_id: Optional[str] = None
    level: str
    message: str
    created_at: datetime

    class Config:
        orm_mode = True

class TaskOut(BaseModel):
    id: str
    user_id: str
    title: str
    goal: str
    status: str
    priority: int
    progress_percent: int
    requires_approval: bool
    error_message: Optional[str] = None
    retry_count: int
    max_retries: int
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        orm_mode = True

class TaskDetail(TaskOut):
    steps: List[TaskStepOut] = []
    logs: List[TaskLogOut] = []

class TaskApprovalRequest(BaseModel):
    action: str = Field(..., regex="^(approve|reject)$", description="'approve' or 'reject'")
    comment: Optional[str] = Field(None, description="Optional feedback or decision rationale")

class TaskControlRequest(BaseModel):
    action: str = Field(..., regex="^(pause|resume|cancel)$", description="'pause', 'resume', or 'cancel'")
