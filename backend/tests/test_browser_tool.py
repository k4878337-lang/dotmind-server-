import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.tools.tool_registry import tool_registry

def test_browser_navigator_registered():
    assert "browser_navigator" in tool_registry._tools
    defn = tool_registry._tools["browser_navigator"]
    assert "Autonomous web browser" in defn.description
    assert "url" in defn.parameters["properties"]
    assert "action" in defn.parameters["properties"]

@pytest.mark.asyncio
async def test_browser_navigator_ssrf_protection():
    # Loopback IP
    res1 = await tool_registry.execute("browser_navigator", {"url": "http://127.0.0.1:8080"})
    assert res1.status == "failed"
    assert "SSRF blocked" in res1.error

    # Cloud metadata
    res2 = await tool_registry.execute("browser_navigator", {"url": "http://169.254.169.254/latest/meta-data"})
    assert res2.status == "failed"
    assert "SSRF blocked" in res2.error

@pytest.mark.asyncio
async def test_browser_navigator_missing_url():
    res = await tool_registry.execute("browser_navigator", {"action": "navigate"})
    assert res.status == "failed"
    assert "Parameter 'url' is required" in res.error

@pytest.mark.asyncio
async def test_browser_navigator_navigate_mock():
    mock_html = """
    <!DOCTYPE html>
    <html>
    <head><title>Test Page Title</title></head>
    <body>
        <h1>Main Heading</h1>
        <h2>Sub Heading</h2>
        <script>console.log("ignore me");</script>
        <p>This is the first paragraph with real text content.</p>
        <p>This is another paragraph explaining browser automation.</p>
    </body>
    </html>
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = mock_html

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await tool_registry.execute("browser_navigator", {
            "url": "https://example.com/article",
            "action": "navigate"
        })
        assert res.status == "succeeded"
        out = res.output
        assert out["title"] == "Test Page Title"
        assert "Main Heading" in out["headings"]
        assert "Sub Heading" in out["headings"]
        assert "This is the first paragraph" in out["text_content"]
        assert "console.log" not in out["text_content"]

@pytest.mark.asyncio
async def test_browser_navigator_extract_links_mock():
    mock_html = """
    <html>
    <head><title>Links Page</title></head>
    <body>
        <a href="https://example.com/about">About Us</a>
        <a href="/pricing">Pricing Plans</a>
    </body>
    </html>
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = mock_html

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await tool_registry.execute("browser_navigator", {
            "url": "https://example.com",
            "action": "extract_links"
        })
        assert res.status == "succeeded"
        out = res.output
        assert out["links_found"] == 2
        assert out["links"][0]["href"] == "https://example.com/about"
        assert out["links"][0]["text"] == "About Us"

@pytest.mark.asyncio
async def test_browser_navigator_search_web_mock():
    mock_search_html = """
    <html><body>
    <a class="result__url" href="https://github.com/dotmind">DotMind GitHub</a>
    <a class="result__snippet">Mobile AI agent repository and architecture.</a>
    </body></html>
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = mock_search_html

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await tool_registry.execute("browser_navigator", {
            "action": "search_web",
            "query": "dotmind ai agent"
        })
        assert res.status == "succeeded"
        out = res.output
        assert out["results_count"] == 1
        assert out["results"][0]["url"] == "https://github.com/dotmind"
