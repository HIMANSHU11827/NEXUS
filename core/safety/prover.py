"""
NEXUS LOGIC PROVER 3.1 — ACTION-AWARE SAFETY GATE
- Blocks dangerous shell/python patterns.
- DISPATCH VERIFICATION: Ensures actions match discovered capabilities.
"""

import ast
import re
import os
from typing import Tuple, List, Any, Optional
from core.discovery import NexusAutoDiscover

SHELL_RULES: List[Tuple[str, str, bool]] = [
    (r"rm\s+-rf?\s+/", "Recursive delete from root", True),
    (r"echo\s+\$[A-Z_]+", "Environment variable leak", True),
    (r"aws\s+configure\s+get", "Read AWS credentials", True),
    (r"cat\s+~/\.ssh/", "Accessing SSH keys", True),
    (r"find\s+/\s+-name\s+.*api.*", "Searching for API keys", True),
    (r"curl\s+.*\.sh\s*\|\s*bash", "Piping remote script to bash", True),
    (r"chmod\s+777", "Insecure permissions", True),
]


class LogicProver:
    """
    FORMAL-LOGIC PROVER 3.2
    - Action-Aware Dispatch Verification.
    - Deep AST Python Inspection.
    """

    strictness: float
    discoverer: NexusAutoDiscover

    def __init__(self, strictness: float = 0.8) -> None:
        self.strictness = strictness
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.discoverer = NexusAutoDiscover(root)

    def verify_action(self, action_tag: str) -> bool:
        """Checks if the action exists in the system grounding."""
        keywords = self.discoverer.get_action_keywords()
        builtins: List[str] = [
            "edit_file",
            "git_cmd",
            "run_tests",
            "lsp_check",
            "symbol_map",
            "web_search",
            "rag_query",
            "swarm_spawn",
            "bash",
            "file_edit",
            "file_write",
        ]
        return action_tag.lower() in [k.lower() for k in keywords + builtins]

    def check_shell(self, command: str) -> Tuple[bool, str]:
        """Check shell command against dangerous patterns."""
        from core.autonomy.risk import CommandRiskScorer

        assessment = CommandRiskScorer().assess(command)
        if assessment.blocked:
            return False, f"BLOCKED: {assessment.summary()}"

        cmd_lower = command.lower().strip()
        for pattern, description, is_regex in SHELL_RULES:
            if is_regex and re.search(pattern, cmd_lower, re.IGNORECASE | re.DOTALL):
                return False, f"BLOCKED: {description}"
        return True, "OK"

    def check_python(self, code: str) -> Tuple[bool, str]:
        """Check Python code using AST inspection."""
        try:
            tree = ast.parse(code)
            forbidden_funcs: set = {
                "eval",
                "exec",
                "os.system",
                "os.popen",
                "subprocess.call",
                "subprocess.run",
            }
            forbidden_modules: set = (
                {"os", "subprocess", "shutil", "socket", "requests"}
                if self.strictness > 0.9
                else set()
            )

            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func_name = ""
                    if isinstance(node.func, ast.Name):
                        func_name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        if isinstance(node.func.value, ast.Name):
                            func_name = f"{node.func.value.id}.{node.func.attr}"

                    if func_name in forbidden_funcs:
                        return False, f"BLOCKED: Dangerous function call '{func_name}'"

                if isinstance(node, (ast.Import, ast.ImportFrom)) and forbidden_modules:
                    names = (
                        [n.name for n in node.names]
                        if isinstance(node, ast.Import)
                        else [node.module]
                    )
                    for name in names:
                        if name in forbidden_modules:
                            return False, f"BLOCKED: Forbidden module import '{name}'"

            return True, "OK"
        except Exception as e:
            return False, f"PARSE_ERROR: {e}"

    def prove_intent(self, action: str, goal: str) -> Tuple[bool, str]:
        """
        [v10.0]: Neural-Symbolic Intent Proof.
        Asks the OMNI_KERNEL to prove that 'action' fulfills 'goal' safely.
        """
        prompt = f"PROVE_LOGIC: Goal is '{goal}'. Action is '{action}'.\nIs this mathematically certain to achieve the goal? Are there side effects? Response: SAFE or FAIL: [reason]"
        
        from core.providers.router import ModelRouter
        from core.intelligence.moa import MixtureOfArchitects
        router = ModelRouter()
        moa = MixtureOfArchitects(router)
        
        import asyncio
        res = asyncio.run(moa.solve(prompt))
        
        if "FAIL" in res.upper():
            return False, res
        return True, "PROVEN"

    def gate(self, command: str, action_context: str = "", intent_goal: str = "") -> str:
        """
        GATES every action with Dispatch Verification + Pattern Blocking + Symbolic Intent Proof.
        """
        if action_context and not self.verify_action(action_context):
            return f"REJECTED: Unauthorized or unknown action '{action_context}'"

        # T1: Static Shell Check
        ok, reason = self.check_shell(command)
        if not ok:
            return reason

        # T2: Static Python Check
        if "import " in command or "def " in command:
            ok, reason = self.check_python(command)
            if not ok:
                return reason

        # T3: [v10.0] Neural-Symbolic Intent Proof
        if intent_goal:
            ok, reason = self.prove_intent(command, intent_goal)
            if not ok:
                return f"LOGIC_PROOF_FAILED: {reason}"

        return "SAFE"


if __name__ == "__main__":
    p = LogicProver()
    print(p.gate("rm -rf /", "bash"))
    print(p.gate("ls -la", "bash"))
    print(p.gate("run_custom", "bash"))
