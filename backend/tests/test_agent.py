import pytest

@pytest.mark.asyncio
async def test_agent_profile_management(client):
    # 1. Register user
    reg_res = await client.post("/api/v1/auth/register", json={
        "email": "agent_owner@dotmind.ai",
        "password": "Password123!",
        "full_name": "Agent Owner"
    })
    token = reg_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Get default profile
    profile_res = await client.get("/api/v1/agent/profile", headers=headers)
    assert profile_res.status_code == 200
    data = profile_res.json()
    assert data["name"] == "DotMind"

    # 3. Update profile
    update_res = await client.put(
        "/api/v1/agent/profile",
        json={
            "name": "DotMind Pro",
            "personality": "Direct, strategic, and concise",
            "instructions": "Always prioritize actionable next steps.",
            "avatar_color": "#8B5CF6"
        },
        headers=headers
    )
    assert update_res.status_code == 200
    updated_data = update_res.json()
    assert updated_data["name"] == "DotMind Pro"
    assert updated_data["avatar_color"] == "#8B5CF6"

    # 4. Fetch updated profile
    get_updated = await client.get("/api/v1/agent/profile", headers=headers)
    assert get_updated.status_code == 200
    assert get_updated.json()["name"] == "DotMind Pro"
