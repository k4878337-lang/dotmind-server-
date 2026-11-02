import json
import pytest
import httpx
from app.config import settings

@pytest.mark.asyncio
async def test_gateway_status_and_authentication(client):
    # Unauthenticated request must fail
    unauth_res = await client.get("/api/v1/gateway/status")
    assert unauth_res.status_code == 401

    # Register & Login user
    res = await client.post("/api/v1/auth/register", json={
        "email": "gateway_tester_status@dotmind.ai",
        "password": "Password123!",
        "full_name": "Gateway Status Tester"
    })
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Authenticated status check
    status_res = await client.get("/api/v1/gateway/status", headers=headers)
    assert status_res.status_code == 200
    data = status_res.json()
    assert "gemini" in data["supported_providers"]
    assert "gemini-2.0-flash" in data["available_models"]

@pytest.mark.asyncio
async def test_model_discovery_success_and_filtering(client, monkeypatch):
    """Test model discovery, pagination, and generateContent filtering."""
    reg = await client.post("/api/v1/auth/register", json={
        "email": "model_disco_user@dotmind.ai",
        "password": "Password123!",
        "full_name": "Model Discovery User"
    })
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    captured_urls = []
    captured_headers = {}

    class MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured_urls.append(str(request.url))
            captured_headers.update(dict(request.headers))

            if "pageToken=page2" in str(request.url):
                mock_body = {
                    "models": [
                        {
                            "name": "models/text-embedding-004",
                            "displayName": "Text Embedding 004",
                            "description": "Embedding model",
                            "supportedGenerationMethods": ["embedContent"]
                        }
                    ]
                }
            else:
                mock_body = {
                    "models": [
                        {
                            "name": "models/gemini-2.0-flash",
                            "displayName": "Gemini 2.0 Flash",
                            "description": "Fast multimodal model",
                            "supportedGenerationMethods": ["generateContent", "countTokens"],
                            "inputTokenLimit": 1048576,
                            "outputTokenLimit": 8192
                        },
                        {
                            "name": "models/imagen-3.0",
                            "displayName": "Imagen 3.0",
                            "description": "Image generation",
                            "supportedGenerationMethods": ["generateImages"]
                        }
                    ],
                    "nextPageToken": "page2"
                }

            return httpx.Response(
                status_code=200,
                headers={"content-type": "application/json"},
                content=json.dumps(mock_body).encode("utf-8")
            )

    orig_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *args, **kwargs: orig_async_client(transport=MockTransport(), *args, **kwargs)
    )

    resp = await client.post(
        "/api/v1/gateway/models",
        json={"provider": "gemini", "api_key": "user_test_key_abc123"},
        headers=headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["total_count"] == 3
    # generateContent filter check
    assert len(data["chat_models"]) == 1
    assert data["chat_models"][0]["id"] == "gemini-2.0-flash"
    assert data["chat_models"][0]["category"] == "chat"
    # verify pagination followed
    assert len(captured_urls) == 2
    assert "pageToken=page2" in captured_urls[1]
    # verify header sent securely
    assert captured_headers.get("x-goog-api-key") == "user_test_key_abc123"

@pytest.mark.asyncio
async def test_model_discovery_error_handling(client, monkeypatch):
    """Test invalid key, 403 permission, and 429 quota handling with key redaction."""
    reg = await client.post("/api/v1/auth/register", json={
        "email": "model_err_user@dotmind.ai",
        "password": "Password123!",
        "full_name": "Model Error User"
    })
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    orig_async_client = httpx.AsyncClient

    # 1. Invalid API Key (HTTP 400)
    class Mock400Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=400,
                json={"error": {"message": "API key not valid. Please pass a valid API key."}}
            )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *a, **kw: orig_async_client(transport=Mock400Transport(), *a, **kw)
    )
    res_400 = await client.post(
        "/api/v1/gateway/models",
        json={"provider": "gemini", "api_key": "bad_key_secret_123"},
        headers=headers
    )
    assert res_400.status_code == 200
    assert res_400.json()["status"] == "error"
    assert "Invalid API key" in res_400.json()["message"]
    assert "bad_key_secret_123" not in res_400.json()["message"]

    # 2. Quota / Rate limit exceeded (HTTP 429)
    class Mock429Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=429,
                json={"error": {"message": "Resource has been exhausted"}}
            )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *a, **kw: orig_async_client(transport=Mock429Transport(), *a, **kw)
    )
    res_429 = await client.post(
        "/api/v1/gateway/models",
        json={"provider": "gemini", "api_key": "exhausted_key_456"},
        headers=headers
    )
    assert res_429.status_code == 200
    assert res_429.json()["status"] == "error"
    assert "quota or rate limit exceeded" in res_429.json()["message"].lower()

@pytest.mark.asyncio
async def test_test_connection_selected_model_and_normalization(client, monkeypatch):
    """Test connection verification with model normalization (models/ prefix stripped)."""
    reg = await client.post("/api/v1/auth/register", json={
        "email": "test_conn_user@dotmind.ai",
        "password": "Password123!",
        "full_name": "Test Connection User"
    })
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    captured_url = []
    orig_async_client = httpx.AsyncClient

    class MockConnTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured_url.append(str(request.url))
            return httpx.Response(
                status_code=200,
                json={"candidates": [{"content": {"parts": [{"text": "pong"}]}}]}
            )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *a, **kw: orig_async_client(transport=MockConnTransport(), *a, **kw)
    )

    # Pass model with 'models/' prefix
    res = await client.post(
        "/api/v1/gateway/test-connection",
        json={
            "provider": "gemini",
            "api_key": "valid_key_789",
            "model": "models/gemini-2.0-flash"
        },
        headers=headers
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "connected"
    assert data["model"] == "gemini-2.0-flash"
    assert "gemini-2.0-flash" in data["message"]
    # Check that URL has /models/gemini-2.0-flash:generateContent (not models/models/...)
    assert "models/gemini-2.0-flash:generateContent" in captured_url[0]
    assert "models/models/" not in captured_url[0]

@pytest.mark.asyncio
async def test_test_connection_404_model_not_found(client, monkeypatch):
    """Test actionable error when requested model returns 404 from Google."""
    reg = await client.post("/api/v1/auth/register", json={
        "email": "test_404_user@dotmind.ai",
        "password": "Password123!",
        "full_name": "404 User"
    })
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    orig_async_client = httpx.AsyncClient

    class Mock404Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=404,
                json={"error": {"message": "models/gemini-non-existent is not found"}}
            )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *a, **kw: orig_async_client(transport=Mock404Transport(), *a, **kw)
    )

    res = await client.post(
        "/api/v1/gateway/test-connection",
        json={
            "provider": "gemini",
            "api_key": "valid_key_789",
            "model": "gemini-non-existent"
        },
        headers=headers
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "error"
    assert data["error_code"] == "MODEL_NOT_FOUND"
    assert "Refresh Models" in data["message"]

@pytest.mark.asyncio
async def test_test_connection_400_unsupported_model(client, monkeypatch):
    """Test HTTP 400 with unsupported model message classifies as UNSUPPORTED_MODEL."""
    reg = await client.post("/api/v1/auth/register", json={
        "email": "test_400_unsupported@dotmind.ai",
        "password": "Password123!",
        "full_name": "400 Unsupported"
    })
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    orig_async_client = httpx.AsyncClient
    class Mock400Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=400,
                json={"error": {"message": "models/imagen-3.0 is not supported for generateContent", "status": "INVALID_ARGUMENT"}}
            )

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: orig_async_client(transport=Mock400Transport(), *a, **kw))

    res = await client.post(
        "/api/v1/gateway/test-connection",
        json={"provider": "gemini", "api_key": "some_key", "model": "imagen-3.0"},
        headers=headers
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "error"
    assert data["error_code"] == "UNSUPPORTED_MODEL"

@pytest.mark.asyncio
async def test_test_connection_400_invalid_request(client, monkeypatch):
    """Test HTTP 400 with malformed request classifies as INVALID_REQUEST (not INVALID_API_KEY)."""
    reg = await client.post("/api/v1/auth/register", json={
        "email": "test_400_malformed@dotmind.ai",
        "password": "Password123!",
        "full_name": "400 Malformed"
    })
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    orig_async_client = httpx.AsyncClient
    class Mock400Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=400,
                json={"error": {"message": "Invalid temperature parameter", "status": "INVALID_ARGUMENT"}}
            )

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: orig_async_client(transport=Mock400Transport(), *a, **kw))

    res = await client.post(
        "/api/v1/gateway/test-connection",
        json={"provider": "gemini", "api_key": "some_key", "model": "gemini-2.0-flash"},
        headers=headers
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "error"
    assert data["error_code"] == "INVALID_REQUEST"

@pytest.mark.asyncio
async def test_test_connection_401_invalid_key(client, monkeypatch):
    """Test HTTP 401 explicitly classifies as INVALID_API_KEY."""
    reg = await client.post("/api/v1/auth/register", json={
        "email": "test_401_user@dotmind.ai",
        "password": "Password123!",
        "full_name": "401 User"
    })
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    orig_async_client = httpx.AsyncClient
    class Mock401Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=401,
                json={"error": {"message": "API key expired", "status": "UNAUTHENTICATED"}}
            )

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: orig_async_client(transport=Mock401Transport(), *a, **kw))

    res = await client.post(
        "/api/v1/gateway/test-connection",
        json={"provider": "gemini", "api_key": "expired_key", "model": "gemini-2.0-flash"},
        headers=headers
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "error"
    assert data["error_code"] == "INVALID_API_KEY"

@pytest.mark.asyncio
async def test_test_connection_403_permission_denied(client, monkeypatch):
    """Test HTTP 403 classifies as PERMISSION_DENIED."""
    reg = await client.post("/api/v1/auth/register", json={
        "email": "test_403_user@dotmind.ai",
        "password": "Password123!",
        "full_name": "403 User"
    })
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    orig_async_client = httpx.AsyncClient
    class Mock403Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=403,
                json={"error": {"message": "Permission denied for project", "status": "PERMISSION_DENIED"}}
            )

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: orig_async_client(transport=Mock403Transport(), *a, **kw))

    res = await client.post(
        "/api/v1/gateway/test-connection",
        json={"provider": "gemini", "api_key": "no_perm_key", "model": "gemini-1.5-pro"},
        headers=headers
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "error"
    assert data["error_code"] == "PERMISSION_DENIED"

@pytest.mark.asyncio
async def test_test_connection_500_upstream(client, monkeypatch):
    """Test HTTP 500 classifies as UPSTREAM_500."""
    reg = await client.post("/api/v1/auth/register", json={
        "email": "test_500_user@dotmind.ai",
        "password": "Password123!",
        "full_name": "500 User"
    })
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    orig_async_client = httpx.AsyncClient
    class Mock500Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=500,
                json={"error": {"message": "Internal server error", "status": "INTERNAL"}}
            )

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: orig_async_client(transport=Mock500Transport(), *a, **kw))

    res = await client.post(
        "/api/v1/gateway/test-connection",
        json={"provider": "gemini", "api_key": "any_key", "model": "gemini-2.0-flash"},
        headers=headers
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "error"
    assert data["error_code"] == "UPSTREAM_500"

@pytest.mark.asyncio
async def test_personal_api_key_stream_header(client, monkeypatch):
    """Verify that passing X-Gemini-Api-Key routes to personal Gemini provider."""
    reg = await client.post("/api/v1/auth/register", json={
        "email": "personal_key_tester@dotmind.ai",
        "password": "Password123!",
        "full_name": "Personal Key Tester"
    })
    token = reg.json()["access_token"]
    
    # Create conversation
    conv_res = await client.post(
        "/api/v1/chat/conversations",
        json={"title": "Personal Key Test"},
        headers={"Authorization": f"Bearer {token}"}
    )
    conv_id = conv_res.json()["id"]

    captured_headers = {}
    captured_url = []
    orig_async_client = httpx.AsyncClient

    class MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            captured_url.append(str(request.url))
            mock_sse = "data: {\"candidates\": [{\"content\": {\"parts\": [{\"text\": \"Response via Personal Key\"}]}}]}\n\n"
            return httpx.Response(
                status_code=200,
                headers={"content-type": "text/event-stream"},
                content=mock_sse.encode("utf-8")
            )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *args, **kwargs: orig_async_client(transport=MockTransport(), *args, **kwargs)
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "X-Gemini-Api-Key": "personal_secret_key_998877",
        "X-Gemini-Model": "gemini-2.0-flash"
    }

    async with client.stream(
        "POST",
        f"/api/v1/chat/conversations/{conv_id}/messages",
        json={"content": "Hello via my own key"},
        headers=headers
    ) as stream_resp:
        assert stream_resp.status_code == 200
        events = []
        async for line in stream_resp.aiter_lines():
            if line.startswith("data: "):
                events.append(line[6:])

    assert captured_headers.get("x-goog-api-key") == "personal_secret_key_998877"
    assert "models/gemini-2.0-flash:streamGenerateContent" in captured_url[0]
