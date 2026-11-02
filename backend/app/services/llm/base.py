from abc import ABC, abstractmethod
from typing import AsyncGenerator, List, Dict, Any, Optional

class BaseLLMProvider(ABC):
    @abstractmethod
    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        system_instruction: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Yields chunks of text as they arrive from the model."""
        pass

    async def generate(
        self,
        messages: List[Dict[str, Any]],
        system_instruction: Optional[str] = None
    ) -> str:
        """Generates a complete response by accumulating streamed chunks."""
        chunks = []
        async for chunk in self.stream_chat(messages, system_instruction):
            chunks.append(chunk)
        return "".join(chunks)

