from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.agent import AgentProfile
from app.schemas.agent import AgentProfileOut, AgentProfileUpdate
from app.config import settings

router = APIRouter(prefix="/agent", tags=["Agent Profile"])

@router.get("/profile", response_model=AgentProfileOut)
async def get_agent_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(AgentProfile).where(AgentProfile.user_id == current_user.id))
    profile = result.scalar_one_or_none()

    if not profile:
        profile = AgentProfile(
            user_id=current_user.id,
            name=settings.DEFAULT_AGENT_NAME,
            instructions=settings.DEFAULT_AGENT_INSTRUCTIONS,
            personality="Concise, proactive, intelligent",
            avatar_color="#6366F1"
        )
        db.add(profile)
        await db.commit()
        await db.refresh(profile)

    return AgentProfileOut.from_orm(profile)

@router.put("/profile", response_model=AgentProfileOut)
async def update_agent_profile(
    payload: AgentProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(AgentProfile).where(AgentProfile.user_id == current_user.id))
    profile = result.scalar_one_or_none()

    if not profile:
        profile = AgentProfile(user_id=current_user.id, instructions="")
        db.add(profile)

    if payload.name is not None:
        profile.name = payload.name
    if payload.personality is not None:
        profile.personality = payload.personality
    if payload.instructions is not None:
        profile.instructions = payload.instructions
    if payload.avatar_color is not None:
        profile.avatar_color = payload.avatar_color

    await db.commit()
    await db.refresh(profile)
    return AgentProfileOut.from_orm(profile)
