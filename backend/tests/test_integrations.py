import pytest

@pytest.mark.asyncio
async def test_list_integrations(client):
    reg = await client.post("/api/v1/auth/register", json={
        "email": "integrations_user@dotmind.ai",
        "password": "Password123!",
        "full_name": "Integration User"
    })
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    res = await client.get("/api/v1/integrations", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    integration_ids = [item["id"] for item in data]
    assert "workspace_sandbox" in integration_ids
    assert "genai_microservice" in integration_ids
    assert "gemini_gateway" in integration_ids
    assert "web_research" in integration_ids
    assert "github_vcs" in integration_ids

@pytest.mark.asyncio
async def test_test_integration_connectivity(client):
    reg = await client.post("/api/v1/auth/register", json={
        "email": "integration_tester@dotmind.ai",
        "password": "Password123!",
        "full_name": "Integration Tester"
    })
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    res = await client.post("/api/v1/integrations/workspace_sandbox/test", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["integration_id"] == "workspace_sandbox"
    assert body["success"] is True
