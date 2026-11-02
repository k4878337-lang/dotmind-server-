import pytest
from app.services.memory_service import memory_service
from app.models.memory import Memory

@pytest.mark.asyncio
async def test_memory_tenant_isolation_in_ai_context(client):
    """Explicitly verify that User A's memories NEVER leak into User B's AI prompt context."""
    # 1. Register User A
    res_a = await client.post("/api/v1/auth/register", json={
        "email": "alice_secret@dotmind.ai",
        "password": "Password123!",
        "full_name": "Alice Secret"
    })
    token_a = res_a.json()["access_token"]
    user_a_id = res_a.json()["user"]["id"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # 2. Register User B
    res_b = await client.post("/api/v1/auth/register", json={
        "email": "bob_eavesdropper@dotmind.ai",
        "password": "Password123!",
        "full_name": "Bob Eavesdropper"
    })
    token_b = res_b.json()["access_token"]
    user_b_id = res_b.json()["user"]["id"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 3. User A stores highly confidential personal notes
    await client.post("/api/v1/memory", json={
        "category": "preference",
        "content": "Alice Top Secret Safe Code: 771239",
        "importance": 5
    }, headers=headers_a)

    # 4. User B queries for 'Safe Code' or 'Secret' via memory search
    b_search = await client.post("/api/v1/memory/search", json={
        "query": "Safe Code Secret",
        "limit": 5
    }, headers=headers_b)
    assert b_search.status_code == 200
    assert len(b_search.json()) == 0, "User B illegally retrieved User A's memory entries via search!"

    # 5. Create conversation for User B and stream message asking for safe code
    conv_b = await client.post("/api/v1/chat/conversations", json={"title": "Inquiry"}, headers=headers_b)
    conv_b_id = conv_b.json()["id"]

    stream_b = await client.post(
        f"/api/v1/chat/conversations/{conv_b_id}/messages",
        json={"content": "What is the Top Secret Safe Code?"},
        headers=headers_b
    )
    assert stream_b.status_code == 200
    b_text = stream_b.text
    # Ensure Alice's secret is never in Bob's stream
    assert "771239" not in b_text, "CRITICAL LEAK: Alice's memory leaked into Bob's chat response!"
