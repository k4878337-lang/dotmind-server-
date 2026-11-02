#!/usr/bin/env python3
import uvicorn
import os
import sys

def main():
    # Ensure current directory is in sys.path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)

    print("=" * 60)
    print("  🧠 DOTMIND AI AGENT BACKEND - FastAPI Server")
    print("  Inspired by OpenAI Dots Interaction Architecture")
    print("=" * 60)
    print("  Starting on: http://0.0.0.0:8000")
    print("  Docs:        http://localhost:8000/docs")
    print("  Health:      http://localhost:8000/health")
    print("=" * 60)

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info"
    )

if __name__ == "__main__":
    main()
