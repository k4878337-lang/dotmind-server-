import os
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.message import Message
from app.models.task import Task
from app.services.memory_service import memory_service
from app.config import settings

class ContextBudgetManager:
    """Manages context window token budgets to prevent overflows and truncations."""
    def __init__(self, max_tokens: int = 4000):
        self.max_tokens = max_tokens

    @staticmethod
    def estimate_tokens(text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // 4)

    def trim_history(self, messages: List[Dict[str, str]], reserved_tokens: int = 1500) -> List[Dict[str, str]]:
        available = self.max_tokens - reserved_tokens
        if available <= 500:
            available = 500

        # Always preserve the most recent user message
        if not messages:
            return []

        trimmed = []
        current_tokens = 0
        # Iterate backwards from newest message
        for msg in reversed(messages):
            msg_tokens = self.estimate_tokens(msg.get("content", ""))
            if current_tokens + msg_tokens <= available:
                trimmed.insert(0, msg)
                current_tokens += msg_tokens
            else:
                break

        # Ensure at least the last message is present
        if not trimmed and messages:
            trimmed = [messages[-1]]

        return trimmed

class ProjectContext:
    """Discovers project structure, active workspace files, and environment stats."""
    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = os.path.realpath(workspace_root or settings.WORKSPACE_ROOT)

    def get_summary(self) -> Dict[str, Any]:
        if not os.path.exists(self.workspace_root):
            return {"exists": False, "root": self.workspace_root}

        structure = []
        file_count = 0
        for root, dirs, files in os.walk(self.workspace_root):
            # Ignore venv, git, gradle caches, build
            dirs[:] = [d for d in dirs if d not in [".venv", ".git", ".gradle", "build", "__pycache__", ".pytest_cache"]]
            rel_dir = os.path.relpath(root, self.workspace_root)
            if rel_dir == ".":
                rel_dir = "/"
            if len(files) > 0 and file_count < 40:
                structure.append(f"{rel_dir}: {', '.join(files[:8])}")
                file_count += len(files)

        return {
            "exists": True,
            "root": self.workspace_root,
            "sample_structure": "\n".join(structure[:10]),
            "primary_stacks": ["Android (Kotlin/Compose)", "Backend (FastAPI/SQLAlchemy)"]
        }

class ContextEngine:
    def __init__(self):
        self.budget_manager = ContextBudgetManager(max_tokens=4000)
        self.project_context = ProjectContext()

    async def build_context(
        self,
        db: AsyncSession,
        user_id: str,
        conversation_id: str,
        current_message: str,
        base_system_prompt: str,
        selected_model: str = "gemini-2.0-flash",
        include_project: bool = False
    ) -> Dict[str, Any]:
        """
        Assembles a comprehensive context including:
        - System instruction + Persona
        - Bounded user memories (isolated to user_id)
        - Active / waiting tasks
        - Project environment summary
        - Trimmed conversation history
        """
        context_sections = [base_system_prompt]

        # 1. Retrieve user memories with relevance scoring
        memory_text = await memory_service.format_memory_context(db, user_id, current_message)
        if memory_text:
            context_sections.append(memory_text)

        # 2. Retrieve active tasks or waiting approvals for this user
        task_query = await db.execute(
            select(Task)
            .where(Task.user_id == user_id, Task.status.in_(["running", "waiting_for_approval"]))
            .order_by(Task.updated_at.desc())
            .limit(3)
        )
        active_tasks = task_query.scalars().all()
        if active_tasks:
            task_lines = ["--- ACTIVE AUTONOMOUS TASKS ---"]
            for t in active_tasks:
                task_lines.append(f"• Task [{t.id[:8]}]: {t.title} (Status: {t.status}, Progress: {t.progress}%)")
            context_sections.append("\n".join(task_lines))

        # 3. Project context if relevant
        if include_project:
            proj = self.project_context.get_summary()
            if proj["exists"]:
                proj_lines = [
                    "--- ACTIVE PROJECT WORKSPACE ---",
                    f"Root: {proj['root']}",
                    f"Tech Stack: {', '.join(proj['primary_stacks'])}",
                    f"Key Files:\n{proj['sample_structure']}"
                ]
                context_sections.append("\n".join(proj_lines))

        final_system_prompt = "\n\n".join(context_sections)
        reserved_tokens = self.budget_manager.estimate_tokens(final_system_prompt)

        # 4. Fetch prior messages in conversation
        history_query = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )
        all_msgs = history_query.scalars().all()
        formatted_history = [
            {"role": m.role, "content": m.content}
            for m in all_msgs if m.role in ["user", "assistant"] and m.content
        ]

        # 5. Trim history within token budget
        trimmed_history = self.budget_manager.trim_history(formatted_history, reserved_tokens=reserved_tokens)

        return {
            "system_instruction": final_system_prompt,
            "messages": trimmed_history,
            "user_id": user_id,
            "model": selected_model,
            "active_tasks_count": len(active_tasks),
            "estimated_tokens": reserved_tokens + sum(self.budget_manager.estimate_tokens(m["content"]) for m in trimmed_history)
        }

context_engine = ContextEngine()
