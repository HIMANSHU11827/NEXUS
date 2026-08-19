"""Project CLI — command-line interface for project folder management.

Commands:
    nexus project init [PATH]       Initialize a project folder
    nexus project select [PATH]     Select a project to work on
    nexus project list [PATH]       Discover projects in a directory
    nexus project info              Show info about the active project
    nexus project validate          Validate the project folder structure
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any

logger = logging.getLogger(__name__)


def init_project_cli(subparsers) -> None:
    """Register project subcommands with the CLI parser."""
    try:
        project_parser = subparsers.add_parser("project", help="Manage project folders")
        project_sub = project_parser.add_subparsers(dest="project_command")

        # nexus project init
        init_parser = project_sub.add_parser("init", help="Initialize a project folder")
        init_parser.add_argument("path", nargs="?", default=".", help="Project directory (default: current)")
        init_parser.add_argument("--name", default="", help="Project name")
        init_parser.add_argument("--description", default="", help="Project description")

        # nexus project select
        select_parser = project_sub.add_parser("select", help="Select a project to work on")
        select_parser.add_argument("path", nargs="?", default=".", help="Project directory (default: current)")

        # nexus project list
        list_parser = project_sub.add_parser("list", help="Discover projects in a directory")
        list_parser.add_argument("path", nargs="?", default=".", help="Search directory (default: current)")
        list_parser.add_argument("--depth", type=int, default=2, help="Search depth (default: 2)")

        # nexus project info
        info_parser = project_sub.add_parser("info", help="Show info about the active project")

        # nexus project validate
        validate_parser = project_sub.add_parser("validate", help="Validate project folder structure")
        validate_parser.add_argument("path", nargs="?", default=".", help="Project directory (default: current)")

    except Exception as exc:
        logger.debug("project CLI registration failed: %s", exc)


def handle_project_command(args) -> Any:
    """Dispatch project subcommand."""
    command = getattr(args, "project_command", None)
    if command == "init":
        return _handle_init(args)
    elif command == "select":
        return _handle_select(args)
    elif command == "list":
        return _handle_list(args)
    elif command == "info":
        return _handle_info(args)
    elif command == "validate":
        return _handle_validate(args)
    else:
        print("project: unknown subcommand. Try: init, select, list, info, validate")
        return None


def _handle_init(args) -> None:
    """Initialize a new project folder."""
    from nexus.project import init_project

    path = os.path.abspath(getattr(args, "path", ".") or ".")
    name = getattr(args, "name", "") or ""
    description = getattr(args, "description", "") or ""

    try:
        project = init_project(path, name=name, description=description)
        print(f"✅ Project initialized at: {project.project_path}")
        print(f"   Instructions: {project.load_instructions()[:80]}...")
        settings = project.load_settings()
        print(f"   Settings: .nexus/project.json")
        print(f"\nEdit NEXUS.md to add project-specific instructions for the AI agent.")
    except Exception as exc:
        print(f"❌ Failed to initialize project: {exc}")


def _handle_select(args) -> None:
    """Select a project to work on."""
    from nexus.project import ProjectFolder, set_active_project

    path = os.path.abspath(getattr(args, "path", ".") or ".")
    try:
        project = ProjectFolder(path)
        info = project.discover()
        set_active_project(project)

        print(f"📂 Selected project: {info.name}")
        print(f"   Path: {info.path}")
        if info.description:
            print(f"   Description: {info.description}")
        if info.instructions_file:
            print(f"   Instructions: {os.path.basename(info.instructions_file)}")
        else:
            print(f"   ⚠️  No instructions file found (create NEXUS.md for project-specific guidance)")
        print(f"   Git: {'yes' if info.has_git else 'no'}")
        print(f"   Files: ~{info.file_count}")

        # Save selection to global state
        state_path = os.path.join(os.path.expanduser("~"), ".nexus", "last_project.json")
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        with open(state_path, "w") as f:
            json.dump({"path": info.path, "name": info.name}, f, indent=2)

    except Exception as exc:
        print(f"❌ Failed to select project: {exc}")


def _handle_list(args) -> None:
    """Discover projects in a directory."""
    from nexus.project import ProjectFolder

    path = os.path.abspath(getattr(args, "path", ".") or ".")
    depth = getattr(args, "depth", 2) or 2

    try:
        projects = ProjectFolder.discover_projects(path, max_depth=depth)
        if not projects:
            print(f"No projects found in {path}")
            return

        print(f"📂 Found {len(projects)} project(s) in {path}:\n")
        for proj in projects:
            marker = "📝" if proj["has_instructions"] else "  "
            git = "🔀" if proj["has_git"] else "  "
            name = proj["name"] or os.path.basename(proj["path"])
            desc = proj["description"][:60] if proj["description"] else ""
            print(f"  {marker} {git} {name}")
            print(f"      {proj['path']}")
            if desc:
                print(f"      {desc}")
            print()
    except Exception as exc:
        print(f"❌ Failed to list projects: {exc}")


def _handle_info(args) -> None:
    """Show info about the active project."""
    from nexus.project import get_active_project, ProjectFolder

    project = get_active_project()
    if project is None:
        # Try to load from last selection
        state_path = os.path.join(os.path.expanduser("~"), ".nexus", "last_project.json")
        if os.path.exists(state_path):
            try:
                with open(state_path) as f:
                    state = json.load(f)
                project = ProjectFolder(state["path"])
            except Exception:
                pass

    if project is None:
        print("No active project. Use `nexus project select <path>` to select one.")
        return

    try:
        info = project.discover()
        print(f"📂 Project: {info.name}")
        print(f"   Path: {info.path}")
        if info.description:
            print(f"   Description: {info.description}")
        print(f"   Instructions: {os.path.basename(info.instructions_file) if info.instructions_file else 'none'}")
        print(f"   Git: {'yes' if info.has_git else 'no'}")
        print(f"   README: {'yes' if info.has_readme else 'no'}")
        print(f"   Docs: {'yes' if info.has_docs else 'no'}")
        print(f"   Files: ~{info.file_count}")

        settings = project.load_settings()
        print(f"\n   Settings:")
        for key, value in settings.items():
            if key != "version" and value:
                print(f"     {key}: {value}")
    except Exception as exc:
        print(f"❌ Failed to get project info: {exc}")


def _handle_validate(args) -> None:
    """Validate project folder structure."""
    from nexus.project import ProjectFolder

    path = os.path.abspath(getattr(args, "path", ".") or ".")
    try:
        project = ProjectFolder(path)
        result = project.validate()

        if result["valid"]:
            print(f"✅ Project folder is valid: {path}")
        else:
            print(f"❌ Project folder has issues: {path}")

        for issue in result.get("issues", []):
            print(f"   ❌ {issue}")
        for warning in result.get("warnings", []):
            print(f"   ⚠️  {warning}")

        if result.get("has_instructions"):
            print(f"   ✅ Has project instructions")
        if result.get("has_git"):
            print(f"   ✅ Has git repository")
        if result.get("has_readme"):
            print(f"   ✅ Has README")
    except Exception as exc:
        print(f"❌ Failed to validate project: {exc}")
