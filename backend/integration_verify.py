#!/usr/bin/env python3
"""
DOTMIND Live End-to-End Integration Verification Script
Performs real HTTP & SSE requests against the running FastAPI backend server.
"""

import sys
import json
import time
import httpx

BASE_URL = "http://127.0.0.1:8000"

def log(msg, status="INFO"):
    symbol = "🔹"
    if status == "OK": symbol = "✅"
    elif status == "ERR": symbol = "❌"
    elif status == "WARN": symbol = "⚠️"
    print(f"{symbol} [{status}] {msg}")

def main():
    print("=" * 65)
    print("  🧠 DOTMIND LIVE INTEGRATION VERIFICATION")
    print(f"  Target Server: {BASE_URL}")
    print("=" * 65)

    client = httpx.Client(timeout=30.0)

    # 1. Health check
    log("Checking /health endpoint...")
    try:
        res = client.get(f"{BASE_URL}/health")
        assert res.status_code == 200, f"Health check failed with {res.status_code}"
        data = res.json()
        assert data.get("status") == "online"
        assert data.get("database") == "healthy"
        log(f"Health verified: service={data.get('service')}, db={data.get('database')}, llm={data.get('llm_provider')}", "OK")
    except Exception as e:
        log(f"Health check failed: {e}", "ERR")
        sys.exit(1)

    # 2. Registration
    timestamp = int(time.time())
    email_a = f"alice_{timestamp}@dotmind.ai"
    email_b = f"bob_{timestamp}@dotmind.ai"
    password = "SuperSecurePassword123!"

    log(f"Registering primary user: {email_a}...")
    res = client.post(f"{BASE_URL}/api/v1/auth/register", json={
        "email": email_a,
        "password": password,
        "full_name": "Alice Integration"
    })
    assert res.status_code == 201, f"Registration failed: {res.text}"
    token_a = res.json()["access_token"]
    user_a_id = res.json()["user"]["id"]
    headers_a = {"Authorization": f"Bearer {token_a}"}
    log(f"User registered with ID: {user_a_id}", "OK")

    # 3. Login
    log("Verifying login endpoint...")
    res = client.post(f"{BASE_URL}/api/v1/auth/login", json={
        "email": email_a,
        "password": password
    })
    assert res.status_code == 200, f"Login failed: {res.text}"
    log("Login credentials verified & JWT issued", "OK")

    # 4. Authenticated conversation creation
    log("Creating authenticated conversation for User A...")
    res = client.post(
        f"{BASE_URL}/api/v1/chat/conversations",
        json={"title": "Integration Test Session"},
        headers=headers_a
    )
    assert res.status_code == 201, f"Conversation creation failed: {res.text}"
    conv_id = res.json()["id"]
    log(f"Conversation created with ID: {conv_id}", "OK")

    # 5. Real-Time SSE Streaming
    log(f"Streaming message to conversation {conv_id}...")
    events_received = []
    tokens_received = []
    
    with client.stream(
        "POST",
        f"{BASE_URL}/api/v1/chat/conversations/{conv_id}/messages",
        json={"content": "What are your core autonomous agent capabilities?"},
        headers=headers_a
    ) as stream_res:
        assert stream_res.status_code == 200, f"Streaming failed with status: {stream_res.status_code}"
        assert "text/event-stream" in stream_res.headers.get("content-type", "")

        for line in stream_res.iter_lines():
            if line.startswith("event: "):
                events_received.append(line[7:].strip())
            elif line.startswith("data: "):
                data_str = line[6:].strip()
                try:
                    parsed = json.loads(data_str)
                    if "token" in parsed:
                        tokens_received.append(parsed["token"])
                except Exception:
                    pass

    log(f"SSE events captured: {set(events_received)}", "OK")
    log(f"Total tokens streamed: {len(tokens_received)}", "OK")
    streamed_text = "".join(tokens_received)
    log(f"Stream preview: {streamed_text[:90]}...", "INFO")
    assert "[DotMind Local Simulator" not in streamed_text, "Simulator header must not pollute user text"
    assert "DotMind" in streamed_text or "assistant" in streamed_text, "Assistant identity must be returned"

    # 6. Verify database persistence
    log("Verifying message persistence in database...")
    res = client.get(f"{BASE_URL}/api/v1/chat/conversations/{conv_id}", headers=headers_a)
    assert res.status_code == 200
    messages = res.json()["messages"]
    assert len(messages) == 2, f"Expected 2 messages (user + assistant), found {len(messages)}"
    log("Conversation history accurately persisted in database", "OK")

    # 7. Per-User Data Isolation Check
    log("Testing security isolation: Registering User B...")
    res = client.post(f"{BASE_URL}/api/v1/auth/register", json={
        "email": email_b,
        "password": password,
        "full_name": "Bob Intruder"
    })
    token_b = res.json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    log("Testing unauthorized access: User B trying to access User A's conversation...")
    res = client.get(f"{BASE_URL}/api/v1/chat/conversations/{conv_id}", headers=headers_b)
    assert res.status_code == 404, f"Security breach: User B accessed User A's conversation! Status: {res.status_code}"
    log("Security boundary enforced: User B received HTTP 404 (Access Denied)", "OK")

    # 8. Unauthenticated request check
    log("Testing unauthenticated request without token...")
    res = client.get(f"{BASE_URL}/api/v1/chat/conversations/{conv_id}")
    assert res.status_code == 401, f"Security breach: Unauthenticated request returned {res.status_code}"
    log("Authentication boundary enforced: Unauthenticated request rejected with HTTP 401", "OK")

    # 9. Persistent Memory Store Check (Stage 2)
    log("Testing Stage 2 Memory Engine: Creating user preference memory...")
    res = client.post(
        f"{BASE_URL}/api/v1/memory",
        json={
            "category": "preference",
            "content": "User prefers dark mode and concise responses.",
            "importance": 5
        },
        headers=headers_a
    )
    assert res.status_code == 201, f"Memory creation failed: {res.text}"
    mem_id = res.json()["id"]
    log(f"Memory created with ID: {mem_id}", "OK")

    # 10. Memory relevance search check
    log("Testing memory relevance search...")
    res = client.post(
        f"{BASE_URL}/api/v1/memory/search",
        json={"query": "dark mode preferences", "limit": 3},
        headers=headers_a
    )
    assert res.status_code == 200
    assert len(res.json()) >= 1
    assert "dark mode" in res.json()[0]["content"]
    log(f"Relevance search matched {len(res.json())} memory entries", "OK")

    # 11. Memory isolation check (User B cannot see or delete User A's memory)
    log("Testing memory isolation: User B trying to access User A's memory...")
    res = client.get(f"{BASE_URL}/api/v1/memory/{mem_id}", headers=headers_b)
    assert res.status_code == 404, "User B illegally accessed User A's memory!"
    res = client.delete(f"{BASE_URL}/api/v1/memory/{mem_id}", headers=headers_b)
    assert res.status_code == 404, "User B illegally deleted User A's memory!"
    log("Memory tenant isolation verified: User B received 404", "OK")

    # 12. Memory deletion by owner
    log("Testing memory deletion by owner...")
    res = client.delete(f"{BASE_URL}/api/v1/memory/{mem_id}", headers=headers_a)
    assert res.status_code == 204
    log("Memory deletion confirmed (HTTP 204)", "OK")

    print("=" * 65)
    print("  🎉 ALL 12 INTEGRATION CHECKS PASSED WITH 100% SUCCESS")
    print("=" * 65)

if __name__ == "__main__":
    main()
