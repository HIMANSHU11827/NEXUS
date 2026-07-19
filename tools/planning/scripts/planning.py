from __future__ import annotations

__version__ = "1.3.0"
import os

from tools.nexus_tools.base_tool import BaseTool, ToolResult


class PlanningTool(BaseTool):
    name = "planning"
    description = "Create a TODO LIST plan and save to todo.md"

    async def execute(self, goal: str, **kwargs) -> ToolResult:
        try:
            if not goal or not goal.strip():
                return ToolResult(success=False, error="Goal is required")
            plan = self._generate_plan(goal.strip())
            if not plan:
                return ToolResult(success=False, error="Could not generate plan from goal")
            todo_path = os.path.join(self.root_dir, "todo.md") if self.root_dir else "todo.md"
            with open(todo_path, "w", encoding="utf-8") as f:
                f.write(plan + "\n")
            return ToolResult(success=True, output=plan, metadata={"file": todo_path})
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def _generate_plan(self, goal: str) -> str:
        gl = goal.lower()
        words = gl.split()
        lines = ["TODO LIST", ""]

        if len(words) > 6 or any(w in gl for w in ("project", "app", "system", "website", "api", "full", "complete", "game", "platform", "tool")):
            lines.append(f"TASK NAME: {goal.strip()}")
            lines.append("")
            phases = self._detect_phases(gl)
            for i, name in enumerate(phases, 1):
                lines.append(f"PHASE {i}: {name}")
                lines.append("")
        else:
            lines.append(f"TASK NAME: {goal.strip()}")
            lines.append("")

        return "\n".join(lines).rstrip()

    @staticmethod
    def _detect_phases(gl: str) -> list:
        phases = []
        has_web = any(w in gl for w in ("web", "website", "site", "frontend", "html", "css", "page", "react", "vue", "angular"))
        has_backend = any(w in gl for w in ("api", "backend", "server", "database", "db", "rest", "graphql", "microservice"))
        has_game = any(w in gl for w in ("game", "dino", "jump", "obstacle", "score", "player", "animation", "sprite"))
        has_data = any(w in gl for w in ("data", "pipeline", "etl", "analysis", "report", "dashboard", "visualization"))
        has_ml = any(w in gl for w in ("model", "train", "ml", "ai", "predict", "classify", "learn", "neural", "deep"))
        has_cli = any(w in gl for w in ("cli", "terminal", "command", "bash", "shell", "script"))
        has_mobile = any(w in gl for w in ("mobile", "android", "ios", "flutter", "react-native", "swift", "kotlin"))
        has_ext = any(w in gl for w in ("extension", "plugin", "addon", "chrome-extension", "browser"))
        has_desktop = any(w in gl for w in ("desktop", "electron", "gui", "tray", "native", "winforms"))
        has_doc = any(w in gl for w in ("doc", "documentation", "readme", "wiki", "guide", "tutorial"))
        has_security = any(w in gl for w in ("security", "audit", "pentest", "vulnerability", "scan", "harden"))

        if has_game:
            phases.extend(["Project Setup", "Core Screen", "Character Controls", "Obstacles & Difficulty", "Game Logic", "Polish"])
        if has_web:
            phases.append("Frontend Setup")
            phases.append("UI Components")
            if not has_game:
                phases.append("State Management")
        if has_backend:
            phases.extend(["Backend Setup", "API Development", "Integration"])
        if has_ml:
            phases.extend(["Data Preparation", "Model Development", "Deployment"])
        if has_data:
            phases.extend(["Data Pipeline", "Analysis & Output"])
        if has_cli:
            phases.append("CLI Structure")
        if has_mobile:
            phases.extend(["App Scaffold", "UI Screens", "Platform Integration", "Store Prep"])
        if has_ext:
            phases.extend(["Extension Skeleton", "Core Functionality", "Permissions & Publishing"])
        if has_desktop:
            phases.extend(["Window Scaffold", "Main Interface", "Native Features", "Packaging"])
        if has_doc:
            phases.extend(["Content Outline", "Draft Sections", "Review & Publish"])
        if has_security:
            phases.extend(["Reconnaissance", "Vulnerability Assessment", "Exploitation Testing", "Reporting"])

        if not phases:
            phases.append("Core Implementation")

        phases.extend(["Testing", "Final Review"])

        seen = []
        return [p for p in phases if not (p in seen or seen.append(p))]
