import re
from typing import Dict, Any, Optional
from app.services.agent.subagents.base import BaseSubAgent
from app.services.tools.tool_registry import tool_registry, ToolResult

class ResearchAgent(BaseSubAgent):
    """Executes information retrieval across GitHub, workspace directory, and search engines."""

    def __init__(self):
        super().__init__(
            name="ResearchAgent",
            role="Information Retrieval & Codebase Exploration",
            description="Searches GitHub repositories, inspects project workspace structures, and discovers files."
        )

    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        task_type = context.get("type", "github")
        query = context.get("query", "").strip()

        if task_type == "github":
            clean_query = query
            for noise in ["search", "find", "github", "repo", "repositories", "for", "look up", "me"]:
                clean_query = re.sub(rf"\b{noise}\b", "", clean_query, flags=re.IGNORECASE)
            clean_query = clean_query.strip() or "android compose"

            tool_res: ToolResult = await tool_registry.execute("github_researcher", {"query": clean_query})
            return {
                "subagent": self.name,
                "tool": "github_researcher",
                "status": tool_res.status,
                "latency_ms": tool_res.latency_ms,
                "data": tool_res.output,
                "error": tool_res.error
            }

        elif task_type == "workspace_inspect":
            subpath = context.get("subpath", "")
            tool_res = await tool_registry.execute("project_inspector", {"subpath": subpath})
            return {
                "subagent": self.name,
                "tool": "project_inspector",
                "status": tool_res.status,
                "latency_ms": tool_res.latency_ms,
                "data": tool_res.output,
                "error": tool_res.error
            }

        elif task_type == "search_files":
            file_pattern = context.get("file_pattern", "*")
            tool_res = await tool_registry.execute("file_searcher", {"query": query, "file_pattern": file_pattern})
            return {
                "subagent": self.name,
                "tool": "file_searcher",
                "status": tool_res.status,
                "latency_ms": tool_res.latency_ms,
                "data": tool_res.output,
                "error": tool_res.error
            }

        return {"subagent": self.name, "status": "failed", "error": f"Unknown research task type: {task_type}"}
