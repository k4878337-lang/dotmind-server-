import httpx
import sys

def verify_after_restart(conv_id: str, token: str):
    client = httpx.Client(timeout=10.0)
    res = client.get(
        f"http://127.0.0.1:8000/api/v1/chat/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    if res.status_code == 200:
        msgs = res.json()["messages"]
        print(f"✅ [SUCCESS] Preserved {len(msgs)} messages across server restart:")
        for m in msgs:
            print(f"   - [{m['role']}]: {m['content'][:60]}...")
        return True
    else:
        print(f"❌ [FAILED] Status {res.status_code}: {res.text}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python test_restart_verification.py <conv_id> <token>")
        sys.exit(1)
    success = verify_after_restart(sys.argv[1], sys.argv[2])
    sys.exit(0 if success else 1)
