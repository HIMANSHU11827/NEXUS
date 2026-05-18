"""
NEXUS WORKFLOW ENGINE 1.0
Defines and executes multi-step task pipelines.
Each workflow is a YAML/dict plan executed sequentially by the LangChain chain.
"""
import sys, os, yaml, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrators.langchain_agents import create_chat_chain
from core.tool_adapters import RegistryTerminalTool as TerminalTool
from core.tool_adapters import RegistryFileTools as NexusFileTools


class NexusWorkflow:
    def __init__(self):
        self.chain = create_chat_chain()
        self.terminal = TerminalTool("./workspace")
        self.files = NexusFileTools("./workspace")

    def run_workflow(self, steps: list) -> dict:
        """
        Execute a list of workflow steps in order.
        Each step is a dict: {type: 'prompt'|'bash'|'write_file', payload: '...'}
        """
        results = {}
        for i, step in enumerate(steps, 1):
            step_type = step.get("type", "prompt")
            payload = step.get("payload", "")
            label = step.get("label", f"step_{i}")

            print(f"\n[Workflow] Step {i}: {label}")

            if step_type == "prompt":
                out = "".join(self.chain.stream({"input": payload}))
                results[label] = out.strip()
                print(out)

            elif step_type == "bash":
                out = self.terminal.execute(payload)
                results[label] = out.strip()
                print(out)

            elif step_type == "write_file":
                filename = step.get("filename", f"output_{i}.txt")
                content = step.get("content", results.get(label, ""))
                msg = self.files.write_file(filename, content)
                results[label] = msg
                print(msg)

            time.sleep(0.1)

        return results

    def run_from_yaml(self, yaml_path: str) -> dict:
        """Load and execute a workflow from a YAML file."""
        with open(yaml_path) as f:
            wf = yaml.safe_load(f)
        return self.run_workflow(wf.get("steps", []))


# ── Example built-in workflows ──────────────────────────────────────────────
WORKFLOW_CODE_PROJECT = [
    {"type": "prompt",     "label": "plan",    "payload": "Create a 3-step plan to build a Python web scraper."},
    {"type": "prompt",     "label": "code",    "payload": "Write the complete Python web scraper code based on the plan."},
    {"type": "write_file", "label": "save",    "filename": "scraper.py", "content": ""},
    {"type": "bash",       "label": "verify",  "payload": "python --version"},
]

WORKFLOW_RESEARCH = [
    {"type": "prompt", "label": "summary",  "payload": "Summarize the key concepts of Autonomous AI Agents in 5 bullet points."},
    {"type": "prompt", "label": "future",   "payload": "What are 3 future directions for Autonomous AI?"},
    {"type": "write_file", "label": "save", "filename": "research_report.md", "content": ""},
]


if __name__ == "__main__":
    wf = NexusWorkflow()
    wf.run_workflow([
        {"type": "prompt", "label": "test", "payload": "Say 'Workflow engine is online' in one sentence."},
        {"type": "bash",   "label": "ls",   "payload": "dir workspace"},
    ])
