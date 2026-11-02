from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.security import get_password_hash, verify_password, create_access_token
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.agent import AgentProfile
from app.schemas.auth import UserRegister, UserLogin, UserOut, Token
from app.config import settings

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(payload: UserRegister, db: AsyncSession = Depends(get_db)):
    # Check if user already exists
    existing_user = await db.execute(select(User).where(User.email == payload.email))
    if existing_user.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email address already exists."
        )

    # Create new user
    new_user = User(
        email=payload.email,
        hashed_password=get_password_hash(payload.password),
        full_name=payload.full_name,
        is_active=True
    )
    db.add(new_user)
    await db.flush()

    # Create default Agent Profile for user
    default_agent = AgentProfile(
        user_id=new_user.id,
        name=settings.DEFAULT_AGENT_NAME,
        instructions=settings.DEFAULT_AGENT_INSTRUCTIONS,
        personality="Concise, proactive, intelligent",
        avatar_color="#6366F1"
    )
    db.add(default_agent)
    await db.commit()
    await db.refresh(new_user)

    # Issue JWT
    token_str = create_access_token({"sub": new_user.id, "email": new_user.email})
    return Token(
        access_token=token_str,
        token_type="bearer",
        user=UserOut.from_orm(new_user)
    )

@router.post("/login", response_model=Token)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive."
        )

    token_str = create_access_token({"sub": user.id, "email": user.email})
    return Token(
        access_token=token_str,
        token_type="bearer",
        user=UserOut.from_orm(user)
    )

@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserOut.from_orm(current_user)
