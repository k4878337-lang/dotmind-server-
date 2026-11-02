import pytest
from app.services.memory_service import memory_service

@pytest.mark.asyncio
async def test_memory_crud_and_isolation(client):
    # 1. Register User A
    res_a = await client.post("/api/v1/auth/register", json={
        "email": "mem_user_a@dotmind.ai",
        "password": "Password123!",
        "full_name": "Memory Alpha"
    })
    token_a = res_a.json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # 2. Register User B
    res_b = await client.post("/api/v1/auth/register", json={
        "email": "mem_user_b@dotmind.ai",
        "password": "Password123!",
        "full_name": "Memory Beta"
    })
    token_b = res_b.json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 3. User A creates a memory entry
    create_res = await client.post(
        "/api/v1/memory",
        json={
            "category": "preference",
            "content": "User prefers concise answers without fluff.",
            "importance": 5
        },
        headers=headers_a
    )
    assert create_res.status_code == 201
    mem_a = create_res.json()
    assert mem_a["category"] == "preference"
    assert mem_a["importance"] == 5
    mem_a_id = mem_a["id"]

    # 4. User A lists memories -> should see 1 memory
    list_a_res = await client.get("/api/v1/memory", headers=headers_a)
    assert list_a_res.status_code == 200
    assert len(list_a_res.json()) == 1
    assert list_a_res.json()[0]["id"] == mem_a_id

    # 5. User B lists memories -> MUST SEE 0 MEMORIES (isolation)
    list_b_res = await client.get("/api/v1/memory", headers=headers_b)
    assert list_b_res.status_code == 200
    assert len(list_b_res.json()) == 0

    # 6. User B attempts to access User A's memory -> MUST BE 404
    get_b_res = await client.get(f"/api/v1/memory/{mem_a_id}", headers=headers_b)
    assert get_b_res.status_code == 404

    # 7. User B attempts to update User A's memory -> MUST BE 404
    put_b_res = await client.put(f"/api/v1/memory/{mem_a_id}", json={"content": "Hacked"}, headers=headers_b)
    assert put_b_res.status_code == 404

    # 8. User B attempts to delete User A's memory -> MUST BE 404
    del_b_res = await client.delete(f"/api/v1/memory/{mem_a_id}", headers=headers_b)
    assert del_b_res.status_code == 404

    # 9. User A updates their memory
    update_res = await client.put(
        f"/api/v1/memory/{mem_a_id}",
        json={"content": "User prefers concise answers with markdown checklists.", "importance": 4},
        headers=headers_a
    )
    assert update_res.status_code == 200
    assert update_res.json()["content"] == "User prefers concise answers with markdown checklists."
    assert update_res.json()["importance"] == 4

    # 10. User A deletes their memory
    del_a_res = await client.delete(f"/api/v1/memory/{mem_a_id}", headers=headers_a)
    assert del_a_res.status_code == 204

    # Verify deleted
    verify_del = await client.get(f"/api/v1/memory/{mem_a_id}", headers=headers_a)
    assert verify_del.status_code == 404

@pytest.mark.asyncio
async def test_memory_search_and_context_injection(client):
    # 1. Register user
    reg_res = await client.post("/api/v1/auth/register", json={
        "email": "search_tester@dotmind.ai",
        "password": "Password123!",
        "full_name": "Search Tester"
    })
    token = reg_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Add multiple memories
    memories = [
        {"category": "project_note", "content": "The backend must run Python with FastAPI and PostgreSQL.", "importance": 5},
        {"category": "preference", "content": "Always format code snippets with full type annotations.", "importance": 4},
        {"category": "decision", "content": "Mobile app is developed natively with Jetpack Compose.", "importance": 5},
        {"category": "fact", "content": "Office headquarters are located in Zurich.", "importance": 2}
    ]
    for m in memories:
        res = await client.post("/api/v1/memory", json=m, headers=headers)
        assert res.status_code == 201

    # 3. Test search for "Jetpack Compose mobile client"
    search_res = await client.post(
        "/api/v1/memory/search",
        json={"query": "Jetpack Compose mobile client", "limit": 2},
        headers=headers
    )
    assert search_res.status_code == 200
    top_results = search_res.json()
    assert len(top_results) > 0
    assert "Jetpack Compose" in top_results[0]["content"]

    # 4. Create a conversation and stream a message
    conv_res = await client.post("/api/v1/chat/conversations", json={"title": "Stack inquiry"}, headers=headers)
    conv_id = conv_res.json()["id"]

    stream_res = await client.post(
        f"/api/v1/chat/conversations/{conv_id}/messages",
        json={"content": "What is our mobile architecture?"},
        headers=headers
    )
    assert stream_res.status_code == 200
    assert "text/event-stream" in stream_res.headers.get("content-type", "")
