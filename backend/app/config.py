import os
from typing import Optional, List
try:
    from pydantic import BaseSettings, validator
except (ImportError, Exception):
    try:
        from pydantic_settings import BaseSettings
        from pydantic import validator
    except (ImportError, Exception):
        from pydantic.v1 import BaseSettings, validator

class Settings(BaseSettings):
    PROJECT_NAME: str = "DOTMIND API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # Environment & Debug
    DOTMIND_ENV: str = os.getenv("DOTMIND_ENV", "development")
    DEBUG: bool = os.getenv("DOTMIND_DEBUG", "true" if os.getenv("DOTMIND_ENV", "development") != "production" else "false").lower() == "true"
    
    # Security & JWT
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dotmind_super_secure_secret_key_change_in_production_991827")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    @validator("SECRET_KEY")
    def validate_secret_key_in_production(cls, v, values):
        env = values.get("DOTMIND_ENV", "development")
        if env == "production":
            if not v or v == "dotmind_super_secure_secret_key_change_in_production_991827" or len(v) < 32:
                raise ValueError("Insecure default SECRET_KEY cannot be used in production environment. Set a strong SECRET_KEY (min 32 chars).")
        return v
    
    # CORS Origins
    CORS_ORIGINS: List[str] = [
        o.strip() for o in os.getenv("DOTMIND_CORS_ORIGINS", "*").split(",") if o.strip()
    ]

    # Workspace Root for Agent Tools & Context
    WORKSPACE_ROOT: str = os.getenv(
        "DOTMIND_WORKSPACE_ROOT",
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    )
    
    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./dotmind.db"
    
    # LLM & GenAI Service Configuration
    DEFAULT_LLM_PROVIDER: str = "gemini"  # "gemini", "mock", "openai"
    USE_GENAI_SERVICE: bool = os.getenv(
        "DOTMIND_USE_GENAI_SERVICE",
        "false" if os.getenv("DOTMIND_TESTING") == "1" else "true"
    ).lower() in ("true", "1", "yes")
    GENAI_SERVICE_URL: str = os.getenv("GENAI_SERVICE_URL", "http://127.0.0.1:8001")
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = "gemini-2.5-flash"
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY", "")
    
    # Agent Defaults
    DEFAULT_AGENT_NAME: str = "DotMind"
    DEFAULT_AGENT_INSTRUCTIONS: str = (
        "You are DotMind, a proactive, intelligent personal mobile AI agent. "
        "You are concise, direct, helpful, and take ownership of user tasks. "
        "Never fabricate tool results or actions you did not perform."
    )

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
