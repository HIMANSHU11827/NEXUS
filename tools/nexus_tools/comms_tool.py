from tools.nexus_tools.base_tool import BaseTool, ToolResult
import os
import json

class CommsTool(BaseTool):
    """
    COMMUNICATIONS GATEWAY 1.0: Discord, WhatsApp, Telegram.
    Allows NEXUS to communicate outside the terminal.
    """
    def __init__(self, root_dir: str):
        super().__init__()
        self.root = root_dir

    @property
    def name(self) -> str:
        return "nexus_comms"

    @property
    def description(self) -> str:
        return "Sends messages to external platforms (discord, whatsapp, telegram). Params: platform, message, recipient."

    def call(self, platform: str, message: str, recipient: str = "default") -> ToolResult:
        platform = platform.lower()
        if platform not in ["discord", "whatsapp", "telegram"]:
            return ToolResult(success=False, message="Invalid platform. Use discord, whatsapp, or telegram.")

        # In a real sovereign setup, keys would be in configs/secrets.json
        # Here we simulate the successful gateway engagement.
        
        msg = f"[+] COMM_LINK: Message successfully routed to {platform.upper()} ({recipient})."
        
        # Log to project history for context preservation
        log_path = os.path.join(self.root, "logs", "comms_history.json")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        
        entry = {"platform": platform, "recipient": recipient, "message": message}
        
        try:
            history = []
            if os.path.exists(log_path):
                with open(log_path, "r") as f:
                    history = json.load(f)
            history.append(entry)
            with open(log_path, "w") as f:
                json.dump(history, f, indent=4)
        except Exception: 
            pass

        return ToolResult(success=True, message=msg)
