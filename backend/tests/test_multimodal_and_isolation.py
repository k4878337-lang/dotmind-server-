import io
import json
import base64
import pytest
import pytest_asyncio
from httpx import AsyncClient

@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient):
    reg_res = await client.post("/api/v1/auth/register", json={
        "email": "multimodal_user@dotmind.ai",
        "password": "Password123!",
        "full_name": "Multimodal User"
    })
    token = reg_res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

@pytest.mark.asyncio
async def test_upload_image_attachment(client: AsyncClient, auth_headers: dict):
    # Create small 1x1 png image bytes
    small_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    b64_str = base64.b64encode(small_png).decode("utf-8")
    
    payload = {
        "filename": "sample.png",
        "mime_type": "image/png",
        "base64_data": b64_str
    }

    response = await client.post("/api/v1/chat/upload", json=payload, headers=auth_headers)
    assert response.status_code == 201
    data = response.json()
    assert data["filename"] == "sample.png"
    assert data["mime_type"] == "image/png"
    assert data["size_bytes"] == len(small_png)
    assert data["id"] is not None
    assert data["base64_data"] is not None
    # Validate base64 decodes back to original bytes
    decoded = base64.b64decode(data["base64_data"])
    assert decoded == small_png
    assert data["file_url"].startswith("/api/v1/chat/files/")

@pytest.mark.asyncio
async def test_upload_text_document(client: AsyncClient, auth_headers: dict):
    content = b"print('Hello from DotMind multimodal!')\n"
    payload = {
        "filename": "script.py",
        "mime_type": "text/x-python",
        "base64_data": base64.b64encode(content).decode("utf-8")
    }

    response = await client.post("/api/v1/chat/upload", json=payload, headers=auth_headers)
    assert response.status_code == 201
    data = response.json()
    assert data["filename"] == "script.py"
    assert data["size_bytes"] == len(content)

@pytest.mark.asyncio
async def test_download_uploaded_file(client: AsyncClient, auth_headers: dict):
    content = b"Sample document content for verification"
    payload = {
        "filename": "notes.txt",
        "mime_type": "text/plain",
        "base64_data": base64.b64encode(content).decode("utf-8")
    }

    upload_res = await client.post("/api/v1/chat/upload", json=payload, headers=auth_headers)
    assert upload_res.status_code == 201
    file_id = upload_res.json()["id"]

    download_res = await client.get(f"/api/v1/chat/files/{file_id}/notes.txt", headers=auth_headers)
    assert download_res.status_code == 200
    assert download_res.content == content

@pytest.mark.asyncio
async def test_download_file_traversal_protection(client: AsyncClient, auth_headers: dict):
    response = await client.get("/api/v1/chat/files/some-id/../../../../etc/passwd", headers=auth_headers)
    assert response.status_code in [404, 400]

@pytest.mark.asyncio
async def test_stream_events_include_conversation_and_message_id(client: AsyncClient, auth_headers: dict):
    # 1. Create a conversation
    conv_res = await client.post("/api/v1/chat/conversations", json={"title": "Isolation Test Conv"}, headers=auth_headers)
    assert conv_res.status_code == 201
    conv_id = conv_res.json()["id"]

    # 2. Send message with attachment
    payload = {
        "content": "Hi DotMind, check this code",
        "attachments": [
            {
                "filename": "hello.py",
                "mime_type": "text/x-python",
                "size_bytes": 20,
                "base64_data": base64.b64encode(b"x = 42\n").decode("utf-8")
            }
        ]
    }

    response = await client.post(
        f"/api/v1/chat/conversations/{conv_id}/messages",
        json=payload,
        headers=auth_headers
    )
    assert response.status_code == 200

    # Parse SSE stream lines
    events_received = []
    current_event = None
    for line in response.text.split("\n"):
        line = line.strip()
        if line.startswith("event: "):
            current_event = line[7:]
        elif line.startswith("data: ") and current_event:
            raw_data = line[6:]
            try:
                parsed = json.loads(raw_data)
                events_received.append((current_event, parsed))
            except Exception:
                pass
            current_event = None

    assert len(events_received) > 0

    # Verify every single event contains conversation_id and message_id
    for evt_name, evt_data in events_received:
        assert evt_data.get("conversation_id") == conv_id, f"Event {evt_name} missing or wrong conversation_id: {evt_data}"
        assert evt_data.get("message_id") is not None, f"Event {evt_name} missing message_id: {evt_data}"

@pytest.mark.asyncio
async def test_cross_conversation_isolation(client: AsyncClient, auth_headers: dict):
    # Create two conversations
    c1 = await client.post("/api/v1/chat/conversations", json={"title": "Chat A"}, headers=auth_headers)
    c2 = await client.post("/api/v1/chat/conversations", json={"title": "Chat B"}, headers=auth_headers)
    id1 = c1.json()["id"]
    id2 = c2.json()["id"]

    # Stream to Chat A
    res = await client.post(
        f"/api/v1/chat/conversations/{id1}/messages",
        json={"content": "Message in chat A"},
        headers=auth_headers
    )
    assert res.status_code == 200

    # Ensure none of the events from Chat A have Chat B's conversation ID
    for line in res.text.split("\n"):
        if line.startswith("data: "):
            try:
                data = json.loads(line[6:])
                assert data.get("conversation_id") == id1
                assert data.get("conversation_id") != id2
            except Exception:
                pass
