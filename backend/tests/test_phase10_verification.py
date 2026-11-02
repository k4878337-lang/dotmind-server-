import pytest
import httpx
from app.services.llm.mock import MockAgentProvider
from app.services.llm.gemini import GeminiProvider, GeminiAPIException
from app.services.llm.router import LLMRouter
from app.services.agent.orchestrator import agent_orchestrator
from app.services.agent.intent_router import intent_router

@pytest.mark.asyncio
async def test_greeting_responses():
    """1 & 2: Test natural greeting and name responses."""
    provider = MockAgentProvider()

    # 'hi'
    chunks = []
    async for c in provider.stream_chat([{"role": "user", "content": "hi"}]):
        chunks.append(c)
    assert "".join(chunks) == "Hi! I'm DotMind. How can I help you today?"

    # 'hello'
    chunks = []
    async for c in provider.stream_chat([{"role": "user", "content": "hello"}]):
        chunks.append(c)
    assert "".join(chunks) == "Hello! I'm DotMind, your personal AI agent. What would you like to work on today?"

    # 'what is your name?'
    chunks = []
    async for c in provider.stream_chat([{"role": "user", "content": "what is your name?"}]):
        chunks.append(c)
    assert "".join(chunks) == "I'm DotMind, your AI assistant."

@pytest.mark.asyncio
async def test_capabilities_question():
    """3: Test truthful capability descriptions."""
    provider = MockAgentProvider()
    chunks = []
    async for c in provider.stream_chat([{"role": "user", "content": "what can you do?"}]):
        chunks.append(c)
    out = "".join(chunks)
    assert "Android & Jetpack Compose" in out
    assert "Technical SEO Auditing" in out
    assert "GitHub Research" in out
    assert "Offline Mode" in out

@pytest.mark.asyncio
async def test_python_error_explanation():
    """4: Test Python error explanation and troubleshooting."""
    provider = MockAgentProvider()
    chunks = []
    async for c in provider.stream_chat([{"role": "user", "content": "Explain this Python error: IndexError: list index out of range"}]):
        chunks.append(c)
    out = "".join(chunks)
    assert "Explanation of IndexError" in out
    assert "How to Fix:" in out
    assert "len" in out or "index" in out

@pytest.mark.asyncio
async def test_missing_gemini_api_key():
    """5: Test error when Gemini API key is missing."""
    provider = GeminiProvider(api_key="", model="gemini-2.0-flash")
    with pytest.raises(GeminiAPIException) as exc_info:
        async for _ in provider.stream_chat([{"role": "user", "content": "test"}]):
            pass
    assert exc_info.value.error_code == "MISSING_API_KEY"

@pytest.mark.asyncio
async def test_invalid_gemini_api_key(monkeypatch):
    """6: Test invalid Gemini API key error handling."""
    class MockErrorTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": {"message": "API_KEY_INVALID"}}, request=request)

    provider = GeminiProvider(api_key="AIzaSy_fake_test_key", model="gemini-2.0-flash")
    monkeypatch.setattr(httpx.AsyncClient, "_transport_for_url", lambda self, url: MockErrorTransport())

    with pytest.raises(GeminiAPIException) as exc_info:
        async for _ in provider.stream_chat([{"role": "user", "content": "test"}]):
            pass
    assert exc_info.value.error_code == "INVALID_API_KEY"

@pytest.mark.asyncio
async def test_unsupported_model(monkeypatch):
    """7: Test unsupported/not found model error handling."""
    class Mock404Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": {"message": "models/non-existent-model is not found"}}, request=request)

    provider = GeminiProvider(api_key="AIzaSy_test_key", model="non-existent-model")
    monkeypatch.setattr(httpx.AsyncClient, "_transport_for_url", lambda self, url: Mock404Transport())

    with pytest.raises(GeminiAPIException) as exc_info:
        async for _ in provider.stream_chat([{"role": "user", "content": "test"}]):
            pass
    assert exc_info.value.error_code == "MODEL_NOT_FOUND"

@pytest.mark.asyncio
async def test_gemini_timeout(monkeypatch):
    """8: Test timeout handling communicating with Gemini."""
    class MockTimeoutTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("Read timed out")

    provider = GeminiProvider(api_key="AIzaSy_test_key", model="gemini-2.0-flash")
    monkeypatch.setattr(httpx.AsyncClient, "_transport_for_url", lambda self, url: MockTimeoutTransport())

    with pytest.raises(GeminiAPIException) as exc_info:
        async for _ in provider.stream_chat([{"role": "user", "content": "test"}]):
            pass
    assert exc_info.value.error_code == "TIMEOUT"

@pytest.mark.asyncio
async def test_no_internal_planning_leakage(monkeypatch):
    """9: Verify that thought parts are skipped and not yielded as answer deltas."""
    sse_data = (
        'data: {"candidates": [{"content": {"parts": [{"thought": true, "text": "Plan: 1. Acknowledge user greeting."}]}}]}\n\n'
        'data: {"candidates": [{"content": {"parts": [{"text": "Hello there!"}]}}]}\n\n'
    )
    class MockThoughtTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=sse_data.encode('utf-8'), headers={"content-type": "text/event-stream"}, request=request)

    provider = GeminiProvider(api_key="AIzaSy_test_key", model="gemini-2.0-flash")
    monkeypatch.setattr(httpx.AsyncClient, "_transport_for_url", lambda self, url: MockThoughtTransport())

    tokens = []
    async for token in provider.stream_chat([{"role": "user", "content": "hi"}]):
        tokens.append(token)

    full = "".join(tokens)
    assert "Plan: 1. Acknowledge" not in full
    assert "Hello there!" in full

def test_intent_classification_and_tool_mapping():
    """10: Verify intent classification maps to correct tools and no fake tools for greetings."""
    hi_intent = intent_router.classify("hi")
    assert hi_intent.category == "GENERAL_CHAT"
    assert len(hi_intent.suggested_tools) == 0

    seo_intent = intent_router.classify("audit my website seo")
    assert seo_intent.category == "SEO_AUDIT"
    assert "seo_analyzer" in seo_intent.suggested_tools

    gh_intent = intent_router.classify("find compose samples on github")
    assert gh_intent.category == "GITHUB_RESEARCH"
    assert "github_researcher" in gh_intent.suggested_tools
