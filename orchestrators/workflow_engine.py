"""
NEXUS WORKFLOW ENGINE 1.0
Defines and executes multi-step task pipelines.
Each workflow is a YAML/dict plan executed sequentially by the LangChain chain.
"""
import sys, os, yaml, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from orchestrators.langchain_agents import create_chat_chain
except Exception:
    create_chat_chain = None

from tool_adapters import RegistryTerminalTool as TerminalTool
from tool_adapters import RegistryFileTools as NexusFileTools


import concurrent.futures

class NexusWorkflow:
    def __init__(self):
        self.chain = create_chat_chain() if create_chat_chain else None
        self.terminal = TerminalTool("./workspace")
        self.files = NexusFileTools("./workspace")

    def run_workflow(self, steps: list) -> dict:
        """
        Execute a list of workflow steps in order.
        Each step is a dict: {type: 'prompt'|'bash'|'write_file'|'parallel', payload: '...'}
        """
        results = {}
        for i, step in enumerate(steps, 1):
            step_type = step.get("type", "prompt")
            payload = step.get("payload", "")
            label = step.get("label", f"step_{i}")

            print(f"\n[Workflow] Step {i}: {label} ({step_type})")

            if step_type == "prompt":
                if self.chain is None:
                    out = "[ERROR]: LangChain LLM environment not available on this python version."
                else:
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

            elif step_type == "parallel":
                sub_steps = step.get("steps", [])
                print(f"[Workflow] Running {len(sub_steps)} sub-steps in parallel...")
                
                def _run_sub_step(sub_idx, sub_step):
                    sub_type = sub_step.get("type", "prompt")
                    sub_payload = sub_step.get("payload", "")
                    sub_label = sub_step.get("label", f"{label}_sub_{sub_idx}")
                    
                    if sub_type == "prompt":
                        if self.chain is None:
                            sub_out = "[ERROR]: LangChain LLM environment not available on this python version."
                        else:
                            sub_out = "".join(self.chain.stream({"input": sub_payload}))
                        return sub_label, sub_out.strip()
                    elif sub_type == "bash":
                        sub_out = self.terminal.execute(sub_payload)
                        return sub_label, sub_out.strip()
                    elif sub_type == "write_file":
                        sub_filename = sub_step.get("filename", f"output_{sub_idx}.txt")
                        sub_content = sub_step.get("content", "")
                        sub_msg = self.files.write_file(sub_filename, sub_content)
                        return sub_label, sub_msg
                    return sub_label, ""

                with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(sub_steps), 8)) as executor:
                    futures = {executor.submit(_run_sub_step, idx, s): s for idx, s in enumerate(sub_steps, 1)}
                    for future in concurrent.futures.as_completed(futures):
                        sub_label, sub_res = future.result()
                        results[sub_label] = sub_res
                        print(f"[{sub_label} finished]")

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
