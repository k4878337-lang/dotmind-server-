from typing import Dict, Any
from app.services.agent.subagents.base import BaseSubAgent
from app.services.tools.tool_registry import tool_registry, ToolResult

class TestingAgent(BaseSubAgent):
    """Executes test suites and parses test outcomes, failures, and coverage."""

    def __init__(self):
        super().__init__(
            name="TestingAgent",
            role="Testing, QA & Test Regression Analysis",
            description="Executes pytest suites, captures exit codes, extracts failure traces, and asserts system invariants."
        )

    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        target = context.get("test_target", "tests/test_phase2_security_and_tools.py")
        res: ToolResult = await tool_registry.execute("test_runner", {"test_target": target})

        passed_count = 0
        failed_count = 0
        summary_str = ""

        if res.output and isinstance(res.output, dict):
            passed_count = res.output.get("passed", 0)
            failed_count = res.output.get("failed", 0)
            summary_str = res.output.get("summary", "")

        return {
            "subagent": self.name,
            "tool": "test_runner",
            "target": target,
            "status": res.status,
            "passed": passed_count,
            "failed": failed_count,
            "latency_ms": res.latency_ms,
            "summary": summary_str or (res.error or "Test execution finished"),
            "data": res.output,
            "error": res.error
        }
