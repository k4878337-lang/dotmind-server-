import re
from typing import Dict, Any, List
from app.services.agent.subagents.base import BaseSubAgent

class ReviewerAgent(BaseSubAgent):
    """Verifies output safety, path security, secret redactions, and human approval boundaries."""

    def __init__(self):
        super().__init__(
            name="ReviewerAgent",
            role="Security, Safety & Policy Review",
            description="Audits tool inputs and results for path traversal, destructive actions, sensitive credentials, and approval requirements."
        )

    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        action_name = context.get("action", "")
        payload = context.get("payload", {})
        text_content = str(payload)

        # 1. Check for credential exposure
        has_credentials = bool(re.search(r"AIzaSy[A-Za-z0-9_-]{33}", text_content))

        # 2. Check for path traversal attempts
        has_traversal = ".." in text_content or "/etc/" in text_content

        # 3. Check for destructive action
        is_destructive = any(w in action_name.lower() for w in ["delete", "remove", "drop", "overwrite_all", "format"])

        # 4. Human approval requirement
        requires_approval = is_destructive or action_name in ["file_writer", "apply_patch"]

        return {
            "subagent": self.name,
            "action_reviewed": action_name,
            "is_safe": not (has_traversal),
            "requires_human_approval": requires_approval,
            "has_credential_exposure": has_credentials,
            "has_traversal_risk": has_traversal,
            "approval_gate": "REQUIRED" if requires_approval else "PASSED"
        }
