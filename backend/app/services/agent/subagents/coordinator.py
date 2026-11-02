from typing import Dict, Any, List, Optional
from app.services.agent.subagents.planner import PlannerAgent
from app.services.agent.subagents.researcher import ResearchAgent
from app.services.agent.subagents.coder import CodingAgent
from app.services.agent.subagents.tester import TestingAgent
from app.services.agent.subagents.reviewer import ReviewerAgent

class MultiAgentCoordinator:
    """Orchestrates modular subagents with iterative ReAct loops."""

    def __init__(self):
        self.planner = PlannerAgent()
        self.researcher = ResearchAgent()
        self.coder = CodingAgent()
        self.tester = TestingAgent()
        self.reviewer = ReviewerAgent()

        self._registry = {
            "PlannerAgent": self.planner,
            "ResearchAgent": self.researcher,
            "CodingAgent": self.coder,
            "TestingAgent": self.tester,
            "ReviewerAgent": self.reviewer
        }

    def list_subagents(self) -> List[Dict[str, str]]:
        return [
            {"name": agent.name, "role": agent.role, "description": agent.description}
            for agent in self._registry.values()
        ]

    async def plan_goal(self, goal: str, category: str) -> Dict[str, Any]:
        """Invokes PlannerAgent to break a goal into steps."""
        return await self.planner.run({"goal": goal, "category": category})

    async def execute_subtask(self, subagent_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatches work to a specific specialized subagent."""
        agent = self._registry.get(subagent_name)
        if not agent:
            return {"status": "failed", "error": f"Subagent '{subagent_name}' not found."}
        return await agent.run(context)

    async def review_action(self, action_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Invokes ReviewerAgent before consequential actions."""
        return await self.reviewer.run({"action": action_name, "payload": payload})

multi_agent_coordinator = MultiAgentCoordinator()
