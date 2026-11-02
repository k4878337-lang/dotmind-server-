from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.core.database import get_db
from app.config import settings

router = APIRouter(tags=["Health & System"])

@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    db_status = "healthy"
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"

    return {
        "status": "online",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.DOTMIND_ENV,
        "database": db_status,
        "llm_provider": settings.DEFAULT_LLM_PROVIDER
    }

@router.get("/api/v1/system/status")
async def system_status(db: AsyncSession = Depends(get_db)):
    return await health_check(db)
