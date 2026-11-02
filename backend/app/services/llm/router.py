from typing import Optional
from app.config import settings
from app.services.llm.base import BaseLLMProvider
from app.services.llm.gemini import GeminiProvider
from app.services.llm.mock import MockAgentProvider

class LLMRouter:
    @staticmethod
    def get_provider(
        provider_name: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None
    ) -> BaseLLMProvider:
        name = (provider_name or settings.DEFAULT_LLM_PROVIDER).lower()
        key_to_use = (api_key or settings.GEMINI_API_KEY or "").strip()
        
        if name == "gemini" and key_to_use:
            return GeminiProvider(api_key=key_to_use, model=model)
        
        # Default or fallback
        return MockAgentProvider()

llm_router = LLMRouter()
