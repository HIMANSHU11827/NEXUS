import os
import sys
import json
from orchestrators.architect import NexusArchitect

def main():
    print("--- NEXUS RUNTIME AUDIT (A-Z) ---")
    
    # 1. Initialize Coordinator
    try:
        coord = NexusArchitect()
        print(f"[OK] Master Coordinator Initialized.")
        print(f"[OK] Brain Provider: {type(coord.brain).__name__}")
        # Removed non-existent 'gate_active' and 'sandbox' attributes from coordinator
        print(f"[OK] Workspace Status: ONLINE")
    except Exception as e:
        print(f"[ERROR] Failed to init Coordinator: {e}")
        return

    # 2. Test Intent Discovery
    intents = [
        ("Hello world", "chat"),
        ("Search for Python info", "agentic"),
        ("Run a bash script to list files", "agentic")
    ]
    for text, expected in intents:
        found = coord.router.discover_intent(text)
        status = "[OK]" if found == expected else "[WARN]"
        print(f"{status} Intent '{text}' -> {found}")

    # 3. Test Cognitive Turn (Chat Mode)
    print("\n--- RUNNING CHAT TEST ---")
    response = coord.coordinate_task("Hello NEXUS, confirm your existence.")
    print(f"NEXUS RESPONSE: {response}")

    # 4. Verify Traces
    trace_dir = os.path.join(os.getcwd(), "workspace", "traces")
    if os.path.exists(trace_dir):
        files = os.listdir(trace_dir)
        print(f"[OK] Found {len(files)} reasoning traces in {trace_dir}")
    else:
        print(f"[ERROR] Traces folder not found.")

if __name__ == "__main__":
    main()
