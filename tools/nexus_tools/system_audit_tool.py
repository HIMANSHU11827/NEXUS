import os
from typing import Dict, Any, List
from tools.nexus_tools.base_tool import BaseTool, ToolResult

class SystemAuditorTool(BaseTool):
    """
    NEXUS SYSTEM AUDITOR 1.0
    Scans for security vulnerabilities and poor coding patterns.
    """
    name = "system_audit"
    description = "Scans the workspace for security flaws, credentials, and poor patterns."

    def __init__(self, root_dir: str):
        super().__init__()
        self.root = root_dir

    def call(self, target_path: str = ".") -> ToolResult:
        findings = []
        full_path = os.path.join(self.root, target_path)
        
        if not os.path.exists(full_path):
            return ToolResult(error=f"Path {target_path} not found.")

        # 1. Hardcoded Secret Scan
        try:
            from security.secret_scanner import SecretScanner
            for finding in SecretScanner(self.root).scan([target_path]):
                findings.append(f"[SECRET_FOUND]: {finding.path}:{finding.line} ({finding.kind})")
        except Exception as e:
            findings.append(f"[SECRET_SCAN_FAILED]: {e}")

        # 2. Dangerous Function Scan
        dangerous_patterns = [
            r"eval\(",
            r"exec\(",
            r"os\.system\(",
            r"subprocess\.Popen\(.*shell=True"
        ]

        try:
            for root, dirs, files in os.walk(full_path):
                if any(ex in root for ex in [".git", "__pycache__", "node_modules", "workspace"]):
                    continue
                for f in files:
                    if f.endswith((".py", ".js", ".ts", ".env", ".yaml", ".yml")):
                        f_path = os.path.join(root, f)
                        try:
                            with open(f_path, "r", encoding="utf-8") as f_obj:
                                content = f_obj.read()
                                for p in dangerous_patterns:
                                    import re
                                    if re.search(p, content):
                                        findings.append(f"[DANGEROUS_FUNC]: {os.path.relpath(f_path, self.root)} -> {p}")
                        except Exception: pass
        except Exception as e:
            return ToolResult(error=str(e))

        summary = "\n".join(findings) if findings else "No critical vulnerabilities found."
        return ToolResult(data=summary)
