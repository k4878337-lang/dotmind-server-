import pytest
from app.models.task import Task
from app.services.task_worker import task_worker

@pytest.mark.asyncio
async def test_task_creation_and_goal_decomposition(client):
    # 1. Register User A
    reg = await client.post("/api/v1/auth/register", json={
        "email": "task_user_a@dotmind.ai",
        "password": "Password123!",
        "full_name": "Task Creator"
    })
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Post high-level goal
    res = await client.post(
        "/api/v1/tasks",
        json={"goal": "Research competitive personal AI architectures and create comparison report in docs/"},
        headers=headers
    )
    assert res.status_code == 201
    task_data = res.json()
    assert task_data["status"] == "queued"
    assert task_data["progress_percent"] == 0
    assert len(task_data["steps"]) >= 4

    # Verify decomposed steps have proper order and tool assignments
    step_tools = [s["tool_name"] for s in task_data["steps"]]
    assert "web_research" in step_tools
    assert "document_reader" in step_tools
    assert any(s["requires_approval"] for s in task_data["steps"])  # file write step requires approval

@pytest.mark.asyncio
async def test_task_step_execution_and_approval_gate(client):
    reg = await client.post("/api/v1/auth/register", json={
        "email": "task_approval_user@dotmind.ai",
        "password": "Password123!",
        "full_name": "Approval Tester"
    })
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create task with goal requiring file modifications
    task_res = await client.post(
        "/api/v1/tasks",
        json={"goal": "Analyze codebase and write new optimization document to disk"},
        headers=headers
    )
    task_id = task_res.json()["id"]

    # Step 1: Info gathering
    step1_res = await client.post(f"/api/v1/tasks/{task_id}/step", headers=headers)
    assert step1_res.status_code == 200
    assert step1_res.json()["steps"][0]["status"] == "completed"

    # Step 2: Synthesis
    step2_res = await client.post(f"/api/v1/tasks/{task_id}/step", headers=headers)
    assert step2_res.status_code == 200
    assert step2_res.json()["steps"][1]["status"] == "completed"

    # Step 3: Consequential action -> must enter waiting_for_approval!
    step3_res = await client.post(f"/api/v1/tasks/{task_id}/step", headers=headers)
    assert step3_res.status_code == 200
    assert step3_res.json()["status"] == "waiting_for_approval"
    assert step3_res.json()["requires_approval"] is True
    waiting_step = step3_res.json()["steps"][2]
    assert waiting_step["status"] == "waiting_for_approval"

    # User approves step
    appr_res = await client.post(
        f"/api/v1/tasks/{task_id}/steps/{waiting_step['id']}/approve",
        json={"action": "approve", "comment": "Approved by user for production"},
        headers=headers
    )
    assert appr_res.status_code == 200
    assert appr_res.json()["approval_status"] == "approved"

    # Step 3 executes after approval
    exec3_res = await client.post(f"/api/v1/tasks/{task_id}/step", headers=headers)
    assert exec3_res.status_code == 200
    assert exec3_res.json()["steps"][2]["status"] == "completed"

    # Step 4 executes -> task finalized
    exec4_res = await client.post(f"/api/v1/tasks/{task_id}/step", headers=headers)
    assert exec4_res.status_code == 200
    assert exec4_res.json()["status"] == "completed"
    assert exec4_res.json()["progress_percent"] == 100

@pytest.mark.asyncio
async def test_task_control_pause_resume_cancel(client):
    reg = await client.post("/api/v1/auth/register", json={
        "email": "task_control_user@dotmind.ai",
        "password": "Password123!",
        "full_name": "Controller"
    })
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    task_res = await client.post("/api/v1/tasks", json={"goal": "Simple task to pause"}, headers=headers)
    task_id = task_res.json()["id"]

    # Pause task
    p_res = await client.post(f"/api/v1/tasks/{task_id}/control", json={"action": "pause"}, headers=headers)
    assert p_res.status_code == 200
    assert p_res.json()["status"] == "paused"

    # Resume task
    r_res = await client.post(f"/api/v1/tasks/{task_id}/control", json={"action": "resume"}, headers=headers)
    assert r_res.status_code == 200
    assert r_res.json()["status"] == "queued"

    # Cancel task
    c_res = await client.post(f"/api/v1/tasks/{task_id}/control", json={"action": "cancel"}, headers=headers)
    assert c_res.status_code == 200
    assert c_res.json()["status"] == "cancelled"

@pytest.mark.asyncio
async def test_task_multi_tenant_isolation(client):
    # Register User 1
    reg1 = await client.post("/api/v1/auth/register", json={
        "email": "tenant_task_1@dotmind.ai",
        "password": "Password123!",
        "full_name": "Tenant 1"
    })
    token1 = reg1.json()["access_token"]

    # Register User 2
    reg2 = await client.post("/api/v1/auth/register", json={
        "email": "tenant_task_2@dotmind.ai",
        "password": "Password123!",
        "full_name": "Tenant 2"
    })
    token2 = reg2.json()["access_token"]

    # User 1 creates task
    t_res = await client.post(
        "/api/v1/tasks",
        json={"goal": "User 1 Confidential Task"},
        headers={"Authorization": f"Bearer {token1}"}
    )
    task_id = t_res.json()["id"]

    # User 2 tries to read User 1's task -> 404 Access Denied
    read_res = await client.get(f"/api/v1/tasks/{task_id}", headers={"Authorization": f"Bearer {token2}"})
    assert read_res.status_code == 404

    # User 2 tries to control User 1's task -> 404 Access Denied
    ctrl_res = await client.post(
        f"/api/v1/tasks/{task_id}/control",
        json={"action": "cancel"},
        headers={"Authorization": f"Bearer {token2}"}
    )
    assert ctrl_res.status_code == 404

    # User 2 lists tasks -> should not include User 1's task
    list_res = await client.get("/api/v1/tasks", headers={"Authorization": f"Bearer {token2}"})
    assert list_res.status_code == 200
    assert task_id not in [t["id"] for t in list_res.json()]
