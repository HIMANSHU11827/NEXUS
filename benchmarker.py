
import os
import sys
import json
from orchestrators.loop import NexusLoop

def test_nexus():
    loop = NexusLoop()
    tasks = [
        "Hello Nexus, state your name and prime directive.",
        "Perform a system audit of the current workspace and list all files in the root.",
        "Explain how the skill_synthesizer works in this system.",
        "Create a new tool called 'weather_tool' in tools/nexus_tools/ that just returns 'Sunny' for now."
    ]
    
    results = []
    for task in tasks:
        print(f"\n[BENCHMARK] Running Task: {task}")
        response = ""
        try:
            for chunk in loop.stream_run(task):
                response += chunk
                print(chunk, end="", flush=True)
            results.append({"task": task, "response": response})
        except Exception as e:
            print(f"\n[BENCHMARK] Task Failed: {e}")
            results.append({"task": task, "error": str(e)})
            
    with open("benchmark_results.json", "w") as f:
        json.dump(results, f, indent=2)

if __name__ == "__main__":
    test_nexus()
