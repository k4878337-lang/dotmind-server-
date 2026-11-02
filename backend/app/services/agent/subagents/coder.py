from typing import Dict, Any, Optional
from app.services.agent.subagents.base import BaseSubAgent
from app.services.tools.tool_registry import tool_registry, ToolResult

class CodingAgent(BaseSubAgent):
    """Handles code inspection, pattern replacement, safe file writing, and diff generation."""

    def __init__(self):
        super().__init__(
            name="CodingAgent",
            role="Code Refactoring & Workspace File Management",
            description="Reads source code, creates unified diffs, writes files with backups, and searches codebases."
        )

    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        action = context.get("action", "read")
        rel_path = context.get("relative_path", "").strip()

        if action == "read":
            max_lines = context.get("max_lines", 120)
            res: ToolResult = await tool_registry.execute("file_reader", {
                "relative_path": rel_path,
                "max_lines": max_lines
            })
            return {
                "subagent": self.name,
                "tool": "file_reader",
                "action": action,
                "path": rel_path,
                "status": res.status,
                "latency_ms": res.latency_ms,
                "data": res.output,
                "error": res.error
            }

        elif action == "diff":
            new_content = context.get("new_content", "")
            res = await tool_registry.execute("diff_generator", {
                "relative_path": rel_path,
                "new_content": new_content
            })
            return {
                "subagent": self.name,
                "tool": "diff_generator",
                "action": action,
                "path": rel_path,
                "status": res.status,
                "latency_ms": res.latency_ms,
                "data": res.output,
                "error": res.error
            }

        elif action == "write":
            content = context.get("content", "")
            create_backup = context.get("create_backup", True)
            res = await tool_registry.execute("file_writer", {
                "relative_path": rel_path,
                "content": content,
                "create_backup": create_backup
            })
            return {
                "subagent": self.name,
                "tool": "file_writer",
                "action": action,
                "path": rel_path,
                "status": res.status,
                "latency_ms": res.latency_ms,
                "data": res.output,
                "error": res.error
            }

        return {"subagent": self.name, "status": "failed", "error": f"Unsupported coding action: {action}"}
