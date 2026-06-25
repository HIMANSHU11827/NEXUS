import asyncio
import os
import sys
from dotenv import load_dotenv

# Load env variables from .env file
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", ".env"))

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from orchestrators.loop import NexusLoop

async def main():
    print("Initializing NexusLoop...")
    loop = NexusLoop()

    # 1. Test fast-path chat
    print("\n--- Testing Fast-Path Chat ---")
    print("User: Hello, who are you?")
    print("Nexus stream:")
    try:
        async for chunk in loop.stream_run("Hello, who are you?"):
            t = chunk.get("type", "?")
            d = chunk.get("data", "")
            if t == "content":
                print(d, end="", flush=True)
            elif t == "status":
                print(f"\n[status: {d.strip()}]", end="", flush=True)
        print()
    except Exception as e:
        print(f"\n[Fast-path error: {e}]")

    # 2. Test full loop execution with task
    print("\n--- Testing Full-Loop Task Execution ---")
    print("User: run a tool to list the current directory")
    print("Nexus stream:")
    try:
        async for chunk in loop.stream_run("run a tool to list the current directory"):
            t = chunk.get("type", "?")
            d = chunk.get("data", "")
            if t == "content":
                print(d, end="", flush=True)
            elif t == "status":
                print(f"\n[status: {d.strip()}]", end="", flush=True)
            elif t == "plan":
                print(f"\n[plan: {d}]", end="", flush=True)
            elif t == "observations":
                print(f"\n[observations: {d}]", end="", flush=True)
        print()
    except Exception as e:
        print(f"\n[Full-loop error: {e}]")

    # 3. Memory persistence check
    print("\n--- Memory Persistence Check ---")
    print(f"Memory entries: {len(loop.memory)}")
    for m in loop.memory:
        role = m.get("role", "?")
        content = m.get("content", "")[:60]
        print(f"  {role}: {content}...")

if __name__ == "__main__":
    asyncio.run(main())
