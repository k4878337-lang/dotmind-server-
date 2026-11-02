import httpx
import json

base_url = "http://127.0.0.1:8000"

# 1. Login
login_resp = httpx.post(
    f"{base_url}/api/v1/auth/login",
    json={"email": "k4878337@gmail.com", "password": "Dotmind@123"}
)
assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
token = login_resp.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# 2. Test the 5 queries
queries = [
    "Test my currently selected model connection. Make a real API request and report the actual result.",
    "List the models actually available to my configured provider. Do not show invented models.",
    "Use the currently selected model and tell me the verified provider and model for this request.",
    "Reply with exactly: DOTMIND_CONNECTION_TEST_731",
    "Explain how you would diagnose a model connection timeout. Do not claim to run diagnostics unless you execute them."
]

for idx, q in enumerate(queries, 1):
    print(f"\n==================== TEST QUERY {idx} ====================")
    print(f"QUERY: {q}")
    # Create conversation
    c_resp = httpx.post(
        f"{base_url}/api/v1/chat/conversations",
        json={"title": f"Test {idx}"},
        headers=headers
    )
    conv_id = c_resp.json()["id"]
    
    # Send message and stream SSE
    answer_deltas = []
    answer_tokens = []
    work_log = None
    evt = ""
    with httpx.Client(timeout=30.0) as client:
        with client.stream(
            "POST",
            f"{base_url}/api/v1/chat/conversations/{conv_id}/messages",
            json={"content": q},
            headers=headers
        ) as response:
            for line in response.iter_lines():
                if line.startswith("event:"):
                    evt = line[6:].strip()
                elif line.startswith("data:"):
                    raw_data = line[5:].strip()
                    try:
                        d = json.loads(raw_data)
                        if evt == "answer_delta":
                            answer_deltas.append(d.get("delta") or "")
                        elif evt == "token":
                            answer_tokens.append(d.get("token") or "")
                        elif evt == "work_log":
                            work_log = d
                        elif evt in ("complete", "done"):
                            c = d.get("content")
                            if c and len(c) > len("".join(answer_deltas)):
                                answer_deltas = [c]
                    except Exception:
                        pass
    full_answer = "".join(answer_deltas) if answer_deltas else "".join(answer_tokens)
    print("--- RESPONSE ---")
    print(full_answer.strip())
    if work_log:
        print("--- WORK LOG SUMMARY ---")
        print(f"Goal: {work_log.get('goal')}")
        tools = [t.get('tool') for t in work_log.get('tools', [])]
        print(f"Tools Used: {tools}")
