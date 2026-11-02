from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.task import (
    TaskCreate,
    TaskOut,
    TaskDetail,
    TaskStepOut,
    TaskApprovalRequest,
    TaskControlRequest
)
from app.services.task_service import task_service

router = APIRouter(prefix="/tasks", tags=["Autonomous Task Engine"])

@router.post("", response_model=TaskDetail, status_code=status.HTTP_201_CREATED)
async def create_autonomous_task(
    payload: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Decomposes a user goal into structured steps and queues the autonomous task."""
    task = await task_service.decompose_goal_and_create_task(db, current_user.id, payload)
    detail = await task_service.get_task_detail(db, task.id, current_user.id)
    return detail

@router.get("", response_model=List[TaskOut])
async def list_tasks(
    status: Optional[str] = Query(None, description="Filter by task status"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Lists autonomous tasks for the authenticated user."""
    tasks = await task_service.get_user_tasks(db, current_user.id, status)
    return tasks

@router.get("/{task_id}", response_model=TaskDetail)
async def get_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Gets task details, ordered execution steps, and live progress logs."""
    task = await task_service.get_task_detail(db, task_id, current_user.id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found or access denied."
        )
    return task

@router.post("/{task_id}/steps/{step_id}/approve", response_model=TaskStepOut)
async def approve_step(
    task_id: str,
    step_id: str,
    payload: TaskApprovalRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Human-in-the-loop approval or rejection for a step waiting for user consent."""
    step = await task_service.handle_approval(
        db,
        task_id=task_id,
        step_id=step_id,
        user_id=current_user.id,
        action=payload.action,
        comment=payload.comment
    )
    if not step:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid task/step ID or step does not require approval."
        )
    return step

@router.post("/{task_id}/control", response_model=TaskDetail)
async def control_task(
    task_id: str,
    payload: TaskControlRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Controls task execution: pause, resume, or cancel."""
    task = await task_service.control_task(
        db,
        task_id=task_id,
        user_id=current_user.id,
        action=payload.action
    )
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found or unauthorized access."
        )
    detail = await task_service.get_task_detail(db, task.id, current_user.id)
    return detail

@router.post("/{task_id}/step", response_model=TaskDetail)
async def execute_single_step(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Triggers immediate single step execution (useful for manual stepping & testing)."""
    task = await task_service.get_task_detail(db, task_id, current_user.id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found or unauthorized access."
        )
    await task_service.process_task_step(db, task)
    detail = await task_service.get_task_detail(db, task.id, current_user.id)
    return detail
