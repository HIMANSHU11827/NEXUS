"""Project folder management — select and manage projects like Claude Code/Cursor/Hermes.

Other AI agents use project folders:
- Claude Code: CLAUDE.md + .claude/settings.json
- Cursor: .cursorrules + .cursor/settings.json
- Hermes: SOUL.md/USER.md + .opencode/workstyle.md
- Codex: workspace with git snapshots

Nexus uses:
- NEXUS.md: project instructions (like CLAUDE.md/.cursorrules)
- .nexus/project.json: project-specific settings
- .nexus/state/: project runtime state (separate from source)

The project folder is the directory the user selects to work on. It becomes
the root_dir for the agent loop, and its NEXUS.md / .nexus/ are loaded
as project-specific context.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Project instruction file names (checked in priority order)
_PROJECT_INSTRUCTION_FILES = (
    "NEXUS.md",
    "AGENTS.md",
    "CLAUDE.md",
    ".cursorrules",
)

# Project settings file
_PROJECT_SETTINGS_FILE = "project.json"

# Default project settings
_DEFAULT_PROJECT_SETTINGS = {
    "version": "1.0",
    "name": "",
    "description": "",
    "instructions_file": "",
    "auto_load_readme": True,
    "auto_load_docs": True,
    "context_budget_chars": 8000,
    "allowed_tools": [],
    "denied_tools": [],
    "sandbox_tier": "normal",
    "permission_mode": "ai_decide",
}


@dataclass
class ProjectInfo:
    """Information about a discovered project."""
    path: str
    name: str
    description: str
    instructions_file: str
    instructions_content: str
    settings: Dict[str, Any]
    has_git: bool
    has_readme: bool
    has_docs: bool
    file_count: int
    last_modified: float


class ProjectFolder:
    """Manages project folder selection and configuration.

    Usage:
        project = ProjectFolder("/path/to/my/project")
        project.discover()  # Find NEXUS.md, settings, etc.
        info = project.info()  # Get project metadata
        instructions = project.load_instructions()  # Get NEXUS.md content
        settings = project.load_settings()  # Get .nexus/project.json
    """

    def __init__(self, project_path: str):
        self.project_path = os.path.abspath(project_path)
        self._info: Optional[ProjectInfo] = None
        self._instructions_cache: Optional[str] = None
        self._settings_cache: Optional[Dict[str, Any]] = None

    # ── Discovery ────────────────────────────────────────────────────────

    def discover(self) -> ProjectInfo:
        """Discover project files and metadata."""
        path = Path(self.project_path)
        if not path.is_dir():
            raise ValueError(f"Not a directory: {self.project_path}")

        # Find instructions file
        instructions_file = ""
        instructions_content = ""
        for filename in _PROJECT_INSTRUCTION_FILES:
            fpath = path / filename
            if fpath.is_file():
                instructions_file = str(fpath)
                try:
                    instructions_content = fpath.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    pass
                break

        # Load settings
        settings = self._load_settings_from_disk()

        # Check for git
        has_git = (path / ".git").is_dir()

        # Check for README
        has_readme = any((path / name).is_file() for name in ("README.md", "readme.md", "README.rst"))

        # Check for docs
        has_docs = (path / "docs").is_dir() or any(
            (path / name).is_file() for name in ("CONTRIBUTING.md", "ARCHITECTURE.md")
        )

        # Count source files
        file_count = 0
        try:
            for _ in path.rglob("*"):
                file_count += 1
                if file_count > 10000:
                    break  # Cap for large repos
        except Exception:
            pass

        # Determine project name
        name = settings.get("name", "") or path.name
        description = settings.get("description", "") or ""

        # Auto-detect name from README if not set
        if not description and has_readme:
            try:
                readme = (path / "README.md").read_text(encoding="utf-8", errors="replace")
                # First non-empty, non-header line
                for line in readme.split("\n"):
                    line = line.strip()
                    if line and not line.startswith("#"):
                        description = line[:200]
                        break
            except Exception:
                pass

        self._info = ProjectInfo(
            path=self.project_path,
            name=name,
            description=description,
            instructions_file=instructions_file,
            instructions_content=instructions_content,
            settings=settings,
            has_git=has_git,
            has_readme=has_readme,
            has_docs=has_docs,
            file_count=file_count,
            last_modified=time.time(),
        )
        self._instructions_cache = instructions_content
        self._settings_cache = settings
        return self._info

    def info(self) -> ProjectInfo:
        """Get project info (discovers if not yet done)."""
        if self._info is None:
            self.discover()
        return self._info

    # ── Instructions ─────────────────────────────────────────────────────

    def load_instructions(self) -> str:
        """Load project instructions from NEXUS.md (or fallback files)."""
        if self._instructions_cache is not None:
            return self._instructions_cache

        path = Path(self.project_path)
        for filename in _PROJECT_INSTRUCTION_FILES:
            fpath = path / filename
            if fpath.is_file():
                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                    self._instructions_cache = content
                    return content
                except Exception:
                    continue
        self._instructions_cache = ""
        return ""

    def create_instructions(self, content: str, filename: str = "NEXUS.md") -> str:
        """Create or overwrite the project instructions file."""
        fpath = os.path.join(self.project_path, filename)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(content)
        self._instructions_cache = content
        self._info = None  # Invalidate cache
        return fpath

    # ── Settings ─────────────────────────────────────────────────────────

    def _nexus_dir(self) -> str:
        """Resolve the .nexus directory inside the project."""
        d = os.path.join(self.project_path, ".nexus")
        os.makedirs(d, exist_ok=True)
        return d

    def _settings_path(self) -> str:
        return os.path.join(self._nexus_dir(), _PROJECT_SETTINGS_FILE)

    def _load_settings_from_disk(self) -> Dict[str, Any]:
        """Load settings from .nexus/project.json."""
        path = self._settings_path()
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return {**_DEFAULT_PROJECT_SETTINGS, **data}
            except Exception:
                pass
        return dict(_DEFAULT_PROJECT_SETTINGS)

    def load_settings(self) -> Dict[str, Any]:
        """Load project settings."""
        if self._settings_cache is not None:
            return self._settings_cache
        self._settings_cache = self._load_settings_from_disk()
        return self._settings_cache

    def save_settings(self, settings: Dict[str, Any]) -> str:
        """Save project settings to .nexus/project.json."""
        path = self._settings_path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        self._settings_cache = settings
        return path

    def update_settings(self, **kwargs: Any) -> Dict[str, Any]:
        """Update specific settings fields."""
        settings = self.load_settings()
        settings.update(kwargs)
        self.save_settings(settings)
        return settings

    # ── Context Loading ──────────────────────────────────────────────────

    def load_project_context(self, max_chars: int = 8000) -> str:
        """Load combined project context (instructions + README + docs).

        This is what gets injected into the system prompt so the agent
        understands the project it's working on.
        """
        parts: List[str] = []

        # 1. Project instructions (NEXUS.md / AGENTS.md / etc.)
        instructions = self.load_instructions()
        if instructions:
            parts.append(f"# Project Instructions\n\n{instructions}")

        # 2. README (if configured)
        settings = self.load_settings()
        if settings.get("auto_load_readme", True):
            readme = self._load_readme()
            if readme:
                parts.append(f"# README\n\n{readme}")

        # 3. Key docs (if configured and project has docs)
        if settings.get("auto_load_docs", True):
            docs = self._load_key_docs()
            if docs:
                parts.append(docs)

        combined = "\n\n---\n\n".join(parts)
        budget = settings.get("context_budget_chars", max_chars)
        if len(combined) > budget:
            combined = combined[:budget] + "\n...[truncated]"
        return combined

    def _load_readme(self) -> str:
        """Load README content."""
        path = Path(self.project_path)
        for name in ("README.md", "readme.md", "README.rst"):
            fpath = path / name
            if fpath.is_file():
                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                    return content[:3000]  # Bound README size
                except Exception:
                    continue
        return ""

    def _load_key_docs(self) -> str:
        """Load key documentation files."""
        path = Path(self.project_path)
        parts: List[str] = []
        for name in ("CONTRIBUTING.md", "ARCHITECTURE.md", "docs/ARCHITECTURE.md"):
            fpath = path / name
            if fpath.is_file():
                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                    if content.strip():
                        parts.append(f"## {name}\n\n{content[:2000]}")
                except Exception:
                    continue
        return "\n\n".join(parts)

    # ── Project Validation ───────────────────────────────────────────────

    def validate(self) -> Dict[str, Any]:
        """Validate the project folder structure."""
        issues: List[str] = []
        warnings: List[str] = []

        path = Path(self.project_path)
        if not path.is_dir():
            issues.append(f"Not a directory: {self.project_path}")
            return {"valid": False, "issues": issues, "warnings": warnings}

        # Check for instructions file
        has_instructions = any((path / f).is_file() for f in _PROJECT_INSTRUCTION_FILES)
        if not has_instructions:
            warnings.append(
                f"No project instructions file found. Create one of: {', '.join(_PROJECT_INSTRUCTION_FILES)}"
            )

        # Check for .nexus directory
        nexus_dir = path / ".nexus"
        if not nexus_dir.is_dir():
            warnings.append("No .nexus/ directory (will be created on first use)")

        # Check for source code
        has_python = any(path.rglob("*.py"))
        has_ts = any(path.rglob("*.ts")) or any(path.rglob("*.tsx"))
        has_js = any(path.rglob("*.js")) or any(path.rglob("*.jsx"))
        if not (has_python or has_ts or has_js):
            warnings.append("No source code files found (.py, .ts, .tsx, .js, .jsx)")

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
            "has_instructions": has_instructions,
            "has_git": (path / ".git").is_dir(),
            "has_readme": any((path / n).is_file() for n in ("README.md", "readme.md")),
        }

    # ── Class Methods ────────────────────────────────────────────────────

    @classmethod
    def from_cwd(cls) -> "ProjectFolder":
        """Create a ProjectFolder from the current working directory."""
        return cls(os.getcwd())

    @classmethod
    def discover_projects(cls, search_path: str = ".", max_depth: int = 3) -> List[Dict[str, Any]]:
        """Discover projects in a directory tree.

        Looks for directories containing NEXUS.md, AGENTS.md, CLAUDE.md,
        .cursorrules, or .git.
        """
        results: List[Dict[str, Any]] = []
        search = Path(search_path).resolve()

        for entry in sorted(search.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name.startswith(".") and entry.name not in (".git",):
                continue
            if entry.name in ("node_modules", "__pycache__", ".venv", "venv", "dist", "build"):
                continue

            # Check if this looks like a project
            has_project_marker = any(
                (entry / f).is_file()
                for f in (*_PROJECT_INSTRUCTION_FILES, ".git")
            )
            if has_project_marker:
                try:
                    info = cls(str(entry)).discover()
                    results.append({
                        "path": str(entry),
                        "name": info.name,
                        "description": info.description[:100],
                        "has_instructions": bool(info.instructions_file),
                        "has_git": info.has_git,
                        "file_count": info.file_count,
                    })
                except Exception:
                    continue

            # Recurse into subdirectories (limited depth)
            if len(results) < 50 and max_depth > 0:
                try:
                    sub_results = cls.discover_projects(str(entry), max_depth - 1)
                    results.extend(sub_results)
                except Exception:
                    continue

            if len(results) >= 50:
                break

        return results


# ── Global Project State ──────────────────────────────────────────────────

_active_project: Optional[ProjectFolder] = None


def get_active_project() -> Optional[ProjectFolder]:
    """Get the currently active project."""
    return _active_project


def set_active_project(project: ProjectFolder) -> None:
    """Set the active project."""
    global _active_project
    _active_project = project


def get_project_root() -> str:
    """Get the active project root, falling back to cwd."""
    if _active_project is not None:
        return _active_project.project_path
    return os.getcwd()


def init_project(path: str = ".", *, name: str = "", description: str = "") -> ProjectFolder:
    """Initialize a new project folder with NEXUS.md and .nexus/project.json."""
    project = ProjectFolder(path)
    project.discover()

    # Create .nexus directory
    nexus_dir = os.path.join(project.project_path, ".nexus")
    os.makedirs(nexus_dir, exist_ok=True)

    # Create NEXUS.md if it doesn't exist
    if not project.load_instructions():
        project_name = name or os.path.basename(project.project_path)
        content = f"""# {project_name}

{description or "Project instructions for Nexus AI agent."}

## Role
You are Nexus, a sovereign AI agent working on this project.

## Behavior
- Be concise and helpful
- Ask clarifying questions when needed
- Proactively solve problems
- Follow project conventions

## Guidelines
- Read existing code before making changes
- Run tests after modifications
- Commit meaningful changes with clear messages
"""
        project.create_instructions(content)

    # Create .nexus/project.json if it doesn't exist
    settings_path = os.path.join(nexus_dir, _PROJECT_SETTINGS_FILE)
    if not os.path.exists(settings_path):
        project.save_settings({
            **_DEFAULT_PROJECT_SETTINGS,
            "name": name or os.path.basename(project.project_path),
            "description": description,
        })

    logger.info("project initialized at %s", project.project_path)
    return project
