import re
from typing import Dict, Any, List
from pydantic import BaseModel, Field

class IntentClassification(BaseModel):
    category: str = Field(..., description="Primary detected category")
    confidence: float = Field(1.0, description="Confidence score 0.0 - 1.0")
    suggested_tools: List[str] = Field(default_factory=list, description="Candidate tools")
    required_skills: List[str] = Field(default_factory=list, description="Referenced skills")
    explanation: str = Field("", description="Why this workflow was chosen")

class IntentRouter:
    """Classifies user messages into specialist workflows and matches appropriate tools and skills."""

    RULES = [
        {
            "category": "GITHUB_RESEARCH",
            "keywords": [r"\bgithub\b", r"\brepositor(y|ies)\b", r"\brepos?\b", r"\breadme\b", r"\bclone\b", r"\bopen[- ]source\b"],
            "tools": ["github_researcher"],
            "skills": ["github-research"],
            "explanation": "User requested public GitHub repository search or inspection."
        },
        {
            "category": "SEO_AUDIT",
            "keywords": [r"\bseo\b", r"\bmeta tag\b", r"\bsitemap\b", r"\brobots\.txt\b", r"\bopengraph\b", r"\branking\b", r"\bcrawlability\b", r"\bstructured data\b"],
            "tools": ["seo_analyzer", "http_tester"],
            "skills": ["website-seo"],
            "explanation": "User requested website SEO audit or metadata optimization."
        },
        {
            "category": "MOBILE_DEV",
            "keywords": [r"\bandroid\b", r"\bcompose\b", r"\bapk\b", r"\bjetpack\b", r"\bgradle\b", r"\bmobile app\b", r"\bactivity\b", r"\bviewmodel\b"],
            "tools": ["project_inspector", "file_reader"],
            "skills": ["android-development", "jetpack-compose-ui"],
            "explanation": "User requested Android mobile application architecture, UI, or build support."
        },
        {
            "category": "ANIMATION",
            "keywords": [r"\banimation\b", r"\bmotion\b", r"\btransition\b", r"\blottie\b", r"\bsvg animation\b", r"\bkeyframes\b"],
            "tools": ["file_reader"],
            "skills": ["mobile-animations", "animation-web"],
            "explanation": "User requested motion design, interactive transitions, or animation system."
        },
        {
            "category": "API_INTEGRATION",
            "keywords": [r"\bapi\b", r"\bendpoint\b", r"\bhttp 4\d\d\b", r"\bhttp 5\d\d\b", r"\bcurl\b", r"\bstatus code\b", r"\bswagger\b", r"\bpostman\b"],
            "tools": ["http_tester"],
            "skills": ["api-integration", "fastapi"],
            "explanation": "User asked about API integration, HTTP status codes, or network troubleshooting."
        },
        {
            "category": "TESTING_QA",
            "keywords": [r"\btest\b", r"\bpytest\b", r"\bunit test\b", r"\blint\b", r"\bqa\b", r"\bregression\b", r"\bverify\b"],
            "tools": ["test_runner"],
            "skills": ["testing-qa"],
            "explanation": "User requested testing, test suite execution, or quality verification."
        },
        {
            "category": "TASK_PLANNING",
            "keywords": [r"\bplan\b", r"\bmulti-step\b", r"\bbreak down\b", r"\bautonomous\b", r"\bexecute task\b", r"\bgoal\b"],
            "tools": ["task_planner"],
            "skills": ["project-planning"],
            "explanation": "User requested multi-step task planning or autonomous goal decomposition."
        },
        {
            "category": "WEBSITE_DEV",
            "keywords": [r"\bwebsite\b", r"\bweb app\b", r"\bnext\.?js\b", r"\btailwind\b", r"\bfrontend\b", r"\bcss\b", r"\bhtml\b", r"\breact\b"],
            "tools": ["project_inspector", "file_reader"],
            "skills": ["web-development", "react-development"],
            "explanation": "User requested web application design, frontend layout, or web development."
        },
        {
            "category": "LOG_INSPECTION",
            "keywords": [r"\bserver\.log\b", r"\blogs?\b", r"\berror log\b", r"\bstack trace\b", r"\bstdout\b", r"\bcrash log\b"],
            "tools": ["log_inspector"],
            "skills": ["debugging"],
            "explanation": "User requested inspection of workspace server or runtime execution logs."
        },
        {
            "category": "CODING",
            "keywords": [r"\bcode\b", r"\bfunction\b", r"\bclass\b", r"\bbug\b", r"\berror\b", r"\bexception\b", r"\brefactor\b", r"\bdebug\b", r"\bsearch\b", r"\bfind in file\b"],
            "tools": ["project_inspector", "file_reader", "file_searcher", "file_writer"],
            "skills": ["debugging", "python-backend"],
            "explanation": "User asked for code development, debugging, file searching, or refactoring."
        }
    ]

    def classify(self, message: str) -> IntentClassification:
        cleaned = message.strip()
        lower = cleaned.lower()

        # Score matching rules based on keyword occurrences
        best_rule = None
        max_matches = 0

        for rule in self.RULES:
            matches = 0
            for pattern in rule["keywords"]:
                if re.search(pattern, lower):
                    matches += 1
            if matches > max_matches:
                max_matches = matches
                best_rule = rule

        if best_rule and max_matches > 0:
            return IntentClassification(
                category=best_rule["category"],
                confidence=min(0.6 + (0.1 * max_matches), 1.0),
                suggested_tools=best_rule["tools"],
                required_skills=best_rule["skills"],
                explanation=best_rule["explanation"]
            )

        # Default fallback
        return IntentClassification(
            category="GENERAL_CHAT",
            confidence=0.9,
            suggested_tools=[],
            required_skills=[],
            explanation="General conversation, explanation, or question."
        )

intent_router = IntentRouter()
