import os
import json
import pytest
import tempfile
import httpx
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select

from app.core.database import Base
from app.models.user import User
from app.models.conversation import Conversation
from app.models.message import Message
from app.core.security import get_password_hash
from app.services.llm.gemini import GeminiProvider
from app.services.llm.mock import MockAgentProvider

@pytest.mark.asyncio
async def test_per_user_data_isolation(client):
    """Verify that User B cannot access, read, post to, or delete User A's conversations."""
    # 1. Register User A
    res_a = await client.post("/api/v1/auth/register", json={
        "email": "user_a@dotmind.ai",
        "password": "PasswordA123!",
        "full_name": "User Alpha"
    })
    token_a = res_a.json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # 2. Register User B
    res_b = await client.post("/api/v1/auth/register", json={
        "email": "user_b@dotmind.ai",
        "password": "PasswordB123!",
        "full_name": "User Beta"
    })
    token_b = res_b.json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 3. User A creates a confidential conversation
    create_res = await client.post(
        "/api/v1/chat/conversations",
        json={"title": "Alpha Confidential Project"},
        headers=headers_a
    )
    conv_a_id = create_res.json()["id"]

    # 4. User B attempts to read User A's conversation -> MUST FAIL (404 / access denied)
    b_read_res = await client.get(f"/api/v1/chat/conversations/{conv_a_id}", headers=headers_b)
    assert b_read_res.status_code == 404
    assert "not found or access denied" in b_read_res.json()["detail"].lower()

    # 5. User B attempts to post a message into User A's conversation -> MUST FAIL (404)
    b_post_res = await client.post(
        f"/api/v1/chat/conversations/{conv_a_id}/messages",
        json={"content": "Malicious intrusion attempt"},
        headers=headers_b
    )
    assert b_post_res.status_code == 404

    # 6. User B attempts to delete User A's conversation -> MUST FAIL (404)
    b_del_res = await client.delete(f"/api/v1/chat/conversations/{conv_a_id}", headers=headers_b)
    assert b_del_res.status_code == 404

    # 7. User B lists conversations -> MUST NOT include User A's conversation
    b_list_res = await client.get("/api/v1/chat/conversations", headers=headers_b)
    assert b_list_res.status_code == 200
    b_conv_ids = [c["id"] for c in b_list_res.json()]
    assert conv_a_id not in b_conv_ids

@pytest.mark.asyncio
async def test_simulator_transparency(client):
    """Confirm that the local simulator gives natural greetings and discloses offline limitations on capabilities."""
    provider = MockAgentProvider()
    
    # Greeting test: Natural without ugly prefix
    chunks = []
    async for chunk in provider.stream_chat([{"role": "user", "content": "Hello DotMind"}], "Test system"):
        chunks.append(chunk)
    greeting_output = "".join(chunks)
    assert "DotMind" in greeting_output
    assert not greeting_output.startswith("[DotMind Local Simulator")

    # Capabilities test: Discloses offline mode
    cap_chunks = []
    async for chunk in provider.stream_chat([{"role": "user", "content": "What can you do?"}], "Test system"):
        cap_chunks.append(chunk)
    cap_output = "".join(cap_chunks)
    assert "Offline Mode" in cap_output

@pytest.mark.asyncio
async def test_gemini_provider_real_http_request(monkeypatch):
    """Verify that the Gemini provider forms a real HTTPS API request when configured."""
    captured_request = {}

    # Define custom mock transport to inspect outgoing HTTP request to Google API
    class MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured_request["url"] = str(request.url)
            captured_request["method"] = request.method
            captured_request["headers"] = dict(request.headers)
            captured_request["body"] = json.loads(request.content.decode("utf-8"))

            # Return realistic SSE response from Gemini API
            mock_sse_data = "data: {\"candidates\": [{\"content\": {\"parts\": [{\"text\": \"Live Gemini Token\"}]}}]}\n\n"
            return httpx.Response(
                status_code=200,
                headers={"content-type": "text/event-stream"},
                content=mock_sse_data.encode("utf-8")
            )

    provider = GeminiProvider(api_key="test_real_api_key_12345", model="gemini-2.5-flash")

    # Monkeypatch httpx.AsyncClient to use our mock transport
    orig_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *args, **kwargs: orig_async_client(transport=MockTransport(), *args, **kwargs)
    )

    tokens = []
    async for token in provider.stream_chat(
        messages=[{"role": "user", "content": "What is 2+2?"}],
        system_instruction="Be accurate."
    ):
        tokens.append(token)

    # Verify request target and structure
    assert captured_request["method"] == "POST"
    assert "generativelanguage.googleapis.com" in captured_request["url"]
    assert captured_request["headers"].get("x-goog-api-key") == "test_real_api_key_12345"
    assert "key=" not in captured_request["url"]
    assert "gemini-2.5-flash:streamGenerateContent" in captured_request["url"]
    assert captured_request["body"]["contents"][0]["parts"][0]["text"] == "What is 2+2?"
    assert captured_request["body"]["systemInstruction"]["parts"][0]["text"] == "Be accurate."
    assert tokens == ["Live Gemini Token"]

@pytest.mark.asyncio
async def test_database_initialization_and_restart_persistence():
    """Verify that tables initialize properly and data persists across complete engine restarts."""
    temp_dir = tempfile.mkdtemp()
    db_file = os.path.join(temp_dir, "test_persistence.db")
    db_url = f"sqlite+aiosqlite:///{db_file}"

    # 1. Start Engine 1 and create records
    engine_1 = create_async_engine(db_url, future=True)
    async_session_1 = async_sessionmaker(engine_1, expire_on_commit=False)

    async with engine_1.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_1() as session:
        user = User(
            id="user-persist-1",
            email="persistent@dotmind.ai",
            hashed_password=get_password_hash("SecretPass123!"),
            full_name="Persistence Tester"
        )
        session.add(user)
        conv = Conversation(
            id="conv-persist-1",
            user_id="user-persist-1",
            title="Persistent Architectural Notes"
        )
        session.add(conv)
        msg = Message(
            id="msg-persist-1",
            conversation_id="conv-persist-1",
            user_id="user-persist-1",
            role="user",
            content="Testing persistence across process restarts."
        )
        session.add(msg)
        await session.commit()

    # Completely dispose Engine 1 (simulate shutdown/restart)
    await engine_1.dispose()

    # 2. Start Engine 2 pointing to the same file
    engine_2 = create_async_engine(db_url, future=True)
    async_session_2 = async_sessionmaker(engine_2, expire_on_commit=False)

    async with async_session_2() as session:
        # Query user
        user_res = await session.execute(select(User).where(User.id == "user-persist-1"))
        persisted_user = user_res.scalar_one_or_none()
        assert persisted_user is not None
        assert persisted_user.email == "persistent@dotmind.ai"

        # Query conversation
        conv_res = await session.execute(select(Conversation).where(Conversation.id == "conv-persist-1"))
        persisted_conv = conv_res.scalar_one_or_none()
        assert persisted_conv is not None
        assert persisted_conv.title == "Persistent Architectural Notes"

        # Query message
        msg_res = await session.execute(select(Message).where(Message.id == "msg-persist-1"))
        persisted_msg = msg_res.scalar_one_or_none()
        assert persisted_msg is not None
        assert persisted_msg.content == "Testing persistence across process restarts."

    await engine_2.dispose()
    if os.path.exists(db_file):
        os.remove(db_file)
    os.rmdir(temp_dir)
