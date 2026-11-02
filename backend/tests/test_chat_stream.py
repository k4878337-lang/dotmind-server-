import pytest

@pytest.mark.asyncio
async def test_conversation_and_chat_streaming(client):
    # 1. Register & get token
    reg_res = await client.post("/api/v1/auth/register", json={
        "email": "agent_user@dotmind.ai",
        "password": "Password123!",
        "full_name": "Agent User"
    })
    token = reg_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Create conversation
    conv_res = await client.post(
        "/api/v1/chat/conversations",
        json={"title": "Test Chat"},
        headers=headers
    )
    assert conv_res.status_code == 201
    conv_id = conv_res.json()["id"]

    # 3. List conversations
    list_res = await client.get("/api/v1/chat/conversations", headers=headers)
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 1

    # 4. Stream a message
    stream_res = await client.post(
        f"/api/v1/chat/conversations/{conv_id}/messages",
        json={"content": "Who are you and what can you do?"},
        headers=headers
    )
    assert stream_res.status_code == 200
    assert "text/event-stream" in stream_res.headers.get("content-type", "")

    # Read SSE stream lines
    lines = stream_res.text.split("\n")
    events = [l for l in lines if l.startswith("event: ")]
    data_lines = [l for l in lines if l.startswith("data: ")]
    assert len(events) > 0
    assert len(data_lines) > 0

    # 5. Verify conversation history has persisted user and assistant messages
    detail_res = await client.get(f"/api/v1/chat/conversations/{conv_id}", headers=headers)
    assert detail_res.status_code == 200
    messages = detail_res.json()["messages"]
    assert len(messages) >= 2
    roles = [m["role"] for m in messages]
    assert "user" in roles
    assert "assistant" in roles
