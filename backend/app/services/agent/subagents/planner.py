import re
from typing import Dict, Any, List
from app.services.agent.subagents.base import BaseSubAgent

class PlannerAgent(BaseSubAgent):
    """Decomposes complex goals into multi-step execution plans and DAGs."""

    def __init__(self):
        super().__init__(
            name="PlannerAgent",
            role="Strategic Decomposition & Planning",
            description="Analyzes goals, maps required tools, determines step dependencies, and sets approval boundaries."
        )

    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        goal = context.get("goal", "").strip()
        intent_cat = context.get("category", "GENERAL_CHAT")

        steps: List[Dict[str, Any]] = []

        if intent_cat == "GITHUB_RESEARCH":
            steps = [
                {"step": 1, "agent": "ResearchAgent", "action": "Query GitHub API for repositories", "tool": "github_researcher"},
                {"step": 2, "agent": "ReviewerAgent", "action": "Filter and rank results by relevance and stars", "tool": None},
                {"step": 3, "agent": "OrchestratorAgent", "action": "Synthesize verified findings into recommendation", "tool": None}
            ]
        elif intent_cat == "TESTING_QA":
            steps = [
                {"step": 1, "agent": "TestingAgent", "action": "Identify target test suites and execute pytest", "tool": "test_runner"},
                {"step": 2, "agent": "ReviewerAgent", "action": "Parse failure traces and analyze exit codes", "tool": None},
                {"step": 3, "agent": "OrchestratorAgent", "action": "Formulate verification and test pass/fail report", "tool": None}
            ]
        elif intent_cat in ["CODING", "MOBILE_DEV"]:
            steps = [
                {"step": 1, "agent": "ResearchAgent", "action": "Inspect workspace files and search codebase", "tool": "file_reader"},
                {"step": 2, "agent": "CodingAgent", "action": "Formulate code changes and generate diff", "tool": "diff_generator"},
                {"step": 3, "agent": "ReviewerAgent", "action": "Verify safety boundaries and human approval gate", "tool": None},
                {"step": 4, "agent": "OrchestratorAgent", "action": "Deliver verified implementation plan", "tool": None}
            ]
        elif intent_cat == "SEO_AUDIT":
            steps = [
                {"step": 1, "agent": "ResearchAgent", "action": "Audit HTML structure, meta tags, and schema", "tool": "seo_analyzer"},
                {"step": 2, "agent": "ReviewerAgent", "action": "Evaluate Core Web Vitals and crawlability", "tool": None},
                {"step": 3, "agent": "OrchestratorAgent", "action": "Synthesize prioritized SEO recommendations", "tool": None}
            ]
        else:
            steps = [
                {"step": 1, "agent": "OrchestratorAgent", "action": "Synthesize direct response from context and long-term memory", "tool": None}
            ]

        return {
            "subagent": self.name,
            "goal": goal,
            "category": intent_cat,
            "step_count": len(steps),
            "steps": steps
        }
