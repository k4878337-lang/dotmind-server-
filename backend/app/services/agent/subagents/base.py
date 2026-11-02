from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class BaseSubAgent(ABC):
    """Base interface for specialized autonomous sub-agents in the DOTMIND system."""

    def __init__(self, name: str, role: str, description: str):
        self.name = name
        self.role = role
        self.description = description

    @abstractmethod
    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Executes the sub-agent's specialized responsibility and returns structured findings."""
        pass
