import pytest

@pytest.mark.asyncio
async def test_user_registration_and_login(client):
    # 1. Register a new user
    register_payload = {
        "email": "test@dotmind.ai",
        "password": "Password123!",
        "full_name": "Test User"
    }
    reg_res = await client.post("/api/v1/auth/register", json=register_payload)
    assert reg_res.status_code == 201
    reg_data = reg_res.json()
    assert "access_token" in reg_data
    assert reg_data["user"]["email"] == "test@dotmind.ai"

    token = reg_data["access_token"]

    # 2. Duplicate registration should fail
    dup_res = await client.post("/api/v1/auth/register", json=register_payload)
    assert dup_res.status_code == 400

    # 3. Login with correct credentials
    login_payload = {
        "email": "test@dotmind.ai",
        "password": "Password123!"
    }
    login_res = await client.post("/api/v1/auth/login", json=login_payload)
    assert login_res.status_code == 200
    assert "access_token" in login_res.json()

    # 4. Login with invalid password should fail
    bad_login_res = await client.post("/api/v1/auth/login", json={
        "email": "test@dotmind.ai",
        "password": "WrongPassword"
    })
    assert bad_login_res.status_code == 401

    # 5. Access /me with token
    me_res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    assert me_res.json()["email"] == "test@dotmind.ai"

    # 6. Access /me without token should be 401
    unauth_res = await client.get("/api/v1/auth/me")
    assert unauth_res.status_code == 401
