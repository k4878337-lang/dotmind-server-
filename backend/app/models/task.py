import uuid
from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.core.datetime_utils import utc_now

class Task(Base):
    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    goal = Column(Text, nullable=False)
    status = Column(String(32), default="queued", nullable=False, index=True)
    # Statuses: queued, running, waiting_for_approval, paused, completed, failed, cancelled
    priority = Column(Integer, default=3, nullable=False)  # 1 (low) - 5 (critical)
    progress_percent = Column(Integer, default=0, nullable=False)
    requires_approval = Column(Boolean, default=False, nullable=False)
    error_message = Column(Text, nullable=True)
    max_retries = Column(Integer, default=3, nullable=False)
    retry_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    user = relationship("User", backref="tasks")
    steps = relationship("TaskStep", back_populates="task", cascade="all, delete-orphan", order_by="TaskStep.step_order")
    logs = relationship("TaskLog", back_populates="task", cascade="all, delete-orphan", order_by="TaskLog.created_at")

class TaskStep(Base):
    __tablename__ = "task_steps"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    step_order = Column(Integer, nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    tool_name = Column(String(64), nullable=True)
    tool_args = Column(Text, nullable=True)  # JSON formatted arguments
    status = Column(String(32), default="pending", nullable=False, index=True)
    # Statuses: pending, running, waiting_for_approval, completed, failed, skipped
    requires_approval = Column(Boolean, default=False, nullable=False)
    approval_status = Column(String(32), default="none", nullable=False)  # none, pending, approved, rejected
    approval_comment = Column(Text, nullable=True)
    result = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    task = relationship("Task", back_populates="steps")

class TaskLog(Base):
    __tablename__ = "task_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    step_id = Column(String(36), nullable=True)
    level = Column(String(16), default="INFO", nullable=False)  # INFO, WARNING, ERROR, STEP, APPROVAL
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    # Relationships
    task = relationship("Task", back_populates="logs")
