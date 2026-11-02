from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.memory import Memory
from app.schemas.memory import MemoryCreate, MemoryUpdate, MemoryOut, MemorySearchQuery
from app.services.memory_service import memory_service

router = APIRouter(prefix="/memory", tags=["Persistent Memory Engine"])

@router.post("", response_model=MemoryOut, status_code=status.HTTP_201_CREATED)
async def create_memory(
    payload: MemoryCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    memory = Memory(
        user_id=current_user.id,
        category=payload.category or "preference",
        content=payload.content,
        importance=payload.importance or 3,
        source_conversation_id=payload.source_conversation_id,
        is_active=True
    )
    db.add(memory)
    await db.commit()
    await db.refresh(memory)
    return MemoryOut.from_orm(memory)

@router.get("", response_model=List[MemoryOut])
async def list_memories(
    category: Optional[str] = Query(None, description="Filter by category (preference, project_note, decision, fact)"),
    search: Optional[str] = Query(None, description="Filter by content substring"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Memory).where(Memory.user_id == current_user.id).order_by(Memory.updated_at.desc())
    if category:
        stmt = stmt.where(Memory.category == category)
    if search:
        stmt = stmt.where(Memory.content.ilike(f"%{search}%"))

    result = await db.execute(stmt)
    memories = result.scalars().all()
    return [MemoryOut.from_orm(m) for m in memories]

@router.post("/search", response_model=List[MemoryOut])
async def search_memories(
    payload: MemorySearchQuery,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    memories = await memory_service.search_relevant_memories(
        db=db,
        user_id=current_user.id,
        query=payload.query,
        category=payload.category,
        limit=payload.limit or 5
    )
    return [MemoryOut.from_orm(m) for m in memories]

@router.get("/{memory_id}", response_model=MemoryOut)
async def get_memory(
    memory_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Memory).where(Memory.id == memory_id, Memory.user_id == current_user.id)
    )
    memory = result.scalar_one_or_none()
    if not memory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory entry not found or access denied."
        )
    return MemoryOut.from_orm(memory)

@router.put("/{memory_id}", response_model=MemoryOut)
async def update_memory(
    memory_id: str,
    payload: MemoryUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Memory).where(Memory.id == memory_id, Memory.user_id == current_user.id)
    )
    memory = result.scalar_one_or_none()
    if not memory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory entry not found or access denied."
        )

    if payload.content is not None:
        memory.content = payload.content.strip()
    if payload.category is not None:
        memory.category = payload.category
    if payload.importance is not None:
        memory.importance = payload.importance
    if payload.is_active is not None:
        memory.is_active = payload.is_active

    await db.commit()
    await db.refresh(memory)
    return MemoryOut.from_orm(memory)

@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Memory).where(Memory.id == memory_id, Memory.user_id == current_user.id)
    )
    memory = result.scalar_one_or_none()
    if not memory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory entry not found."
        )

    await db.delete(memory)
    await db.commit()
    return None
