import pytest
import json
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.agent.context_engine import ContextBudgetManager, ContextEngine, ProjectContext
from app.services.agent.intent_router import IntentRouter
from app.services.tools.tool_registry import ToolRegistry
from app.services.skills.skills_catalogue import SkillsCatalogue
from app.services.agent.orchestrator import AgentOrchestrator


@pytest.mark.asyncio
async def test_context_budget_manager():
    budget_mgr = ContextBudgetManager(max_tokens=500)
    
    # Estimate tokens
    assert budget_mgr.estimate_tokens("Hello world") > 0

    # Trimming conversation history
    long_history = [
        {"role": "user", "content": "Initial question " + ("word " * 50)},
        {"role": "assistant", "content": "Long answer " + ("word " * 150)},
        {"role": "user", "content": "Second question " + ("word " * 50)},
        {"role": "assistant", "content": "Second answer " + ("word " * 100)},
        {"role": "user", "content": "Final short question?"}
    ]
    
    trimmed = budget_mgr.trim_history(long_history, reserved_tokens=100)
    assert len(trimmed) > 0
    # Must preserve the latest user question
    assert trimmed[-1]["content"] == "Final short question?"


@pytest.mark.asyncio
async def test_project_context_summary():
    proj = ProjectContext(workspace_root="/data/user/0/com.termux/files/home/projects/dotmind")
    summary = proj.get_summary()
    assert summary["exists"] is True
    assert "Android (Kotlin/Compose)" in summary["primary_stacks"]


def test_intent_router_classification():
    router = IntentRouter()
    
    # GitHub Research
    res_github = router.classify("Find popular GitHub repositories for Jetpack Compose animations")
    assert res_github.category == "GITHUB_RESEARCH"
    assert "github_researcher" in res_github.suggested_tools

    # SEO Audit
    res_seo = router.classify("Audit the SEO metadata and meta tags for my website")
    assert res_seo.category == "SEO_AUDIT"
    assert "seo_analyzer" in res_seo.suggested_tools

    # Mobile Dev
    res_mobile = router.classify("Build a Jetpack Compose screen with BottomSheet in Kotlin")
    assert res_mobile.category == "MOBILE_DEV"

    # Animation
    res_anim = router.classify("How to add a smooth Lottie spring animation to Compose button?")
    assert res_anim.category == "ANIMATION"

    # API Integration
    res_api = router.classify("How to call this REST endpoint with bearer token and handle 401 error?")
    assert res_api.category == "API_INTEGRATION"

    # Coding
    res_code = router.classify("Please debug this Python function and fix the KeyError exception")
    assert res_code.category == "CODING"


@pytest.mark.asyncio
async def test_tool_registry_project_inspector_and_file_reader():
    registry = ToolRegistry()
    
    # 1. Project inspector
    inspect_res = await registry.execute("project_inspector", {"subpath": "backend"})
    assert inspect_res.status == "succeeded"
    assert inspect_res.output["total_items"] > 0
    assert "app" in inspect_res.output["files_and_dirs"]

    # 2. File reader
    read_res = await registry.execute("file_reader", {"relative_path": "backend/app/main.py", "max_lines": 20})
    assert read_res.status == "succeeded"
    assert "FastAPI" in read_res.output["content"]

    # 3. Traversal protection
    jail_res = await registry.execute("file_reader", {"relative_path": "../../etc/passwd"})
    assert jail_res.status == "failed"
    assert "Directory traversal attempt blocked" in jail_res.error


@pytest.mark.asyncio
async def test_tool_registry_seo_analyzer():
    registry = ToolRegistry()
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <title>DotMind - Mobile AI Agent</title>
        <meta name="description" content="Personal Autonomous AI Agent for Android">
        <meta property="og:title" content="DotMind Agent">
        <meta property="og:image" content="https://dotmind.ai/banner.png">
        <link rel="canonical" href="https://dotmind.ai">
    </head>
    <body>
        <h1>Welcome to DotMind</h1>
        <img src="logo.png" alt="DotMind Logo">
        <img src="banner.png">
    </body>
    </html>
    """
    res = await registry.execute("seo_analyzer", {"html_content": html_content})
    assert res.status == "succeeded"
    data = res.output
    assert data["title"] == "DotMind - Mobile AI Agent"
    assert data["description"] == "Personal Autonomous AI Agent for Android"
    assert data["h1_count"] == 1
    assert data["seo_score"] >= 80


@pytest.mark.asyncio
async def test_skills_catalogue():
    catalogue = SkillsCatalogue()
    
    skills = catalogue.list_all()
    assert len(skills) >= 5
    
    # Skill retrieval
    compose_guide = catalogue.get("android-development")
    assert compose_guide is not None
    assert "Compose" in compose_guide.description

    # Search
    matched = catalogue.search("SEO")
    assert any(s.name == "website-seo" for s in matched)


@pytest.mark.asyncio
async def test_orchestrator_agent_stream():
    orchestrator = AgentOrchestrator()
    
    # Mock AsyncSession
    mock_db = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_db_result = MagicMock()
    mock_db_result.scalars.return_value = mock_scalars
    mock_db.execute.return_value = mock_db_result
    
    events = []
    async for event in orchestrator.run_agent_loop(
        db=mock_db,
        user_id="test_user",
        conversation_id="conv-1",
        user_message="What is DotMind and how do your tools work?",
        base_instructions="You are DotMind personal AI agent."
    ):
        events.append(event)
    
    event_types = [e["event"] for e in events]
    assert "thought" in event_types
    assert "token" in event_types
    assert len(events) >= 2
    # Verify thought content
    thought_event = next(e for e in events if e["event"] == "thought")
    thought_data = json.loads(thought_event["data"])
    assert "intent" in thought_data
