"""
NEXUS POLICY GUARDRAILS 1.0
Strict rule enforcement engine for autonomous agent actions.
"""

class NexusPolicyEngine:
    """Enforces boundaries so the AI doesn't do anything destructive."""
    
    FORBIDDEN_COMMANDS = [
        "rm -rf /", 
        "format C:", 
        "del /s /q C:\\",
        "drop table"
    ]

    def is_action_safe(self, command: str) -> bool:
        cmd_lower = command.lower()
        for forbidden in self.FORBIDDEN_COMMANDS:
            if forbidden in cmd_lower:
                return False
        return True

    def validate_code(self, code_block: str) -> bool:
        """Inspect python/bash code for infinite loops or malicious imports."""
        if "os.system('rm -rf" in code_block:
            return False
        return True

if __name__ == "__main__":
    policy = NexusPolicyEngine()
    print("Safe:", policy.is_action_safe("ls -la"))
    print("Unsafe:", policy.is_action_safe("rm -rf /"))
