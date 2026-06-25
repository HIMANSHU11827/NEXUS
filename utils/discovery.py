"""NEXUS Auto-Discovery — scans project for modules, tools, skills, and components."""

import os
import json
from typing import Dict, List, Any


class NexusAutoDiscover:
    """Auto-discovers NEXUS components: tools, skills, evolution modules, plugins."""

    def __init__(self, root_dir: str = "."):
        self.root = root_dir

    def discover_tools(self) -> List[Dict[str, Any]]:
        tools_dir = os.path.join(self.root, "tools")
        result = []
        if not os.path.isdir(tools_dir):
            return result
        for name in sorted(os.listdir(tools_dir)):
            if name.startswith(("_", ".", "nexus_tools")):
                continue
            tool_dir = os.path.join(tools_dir, name)
            if not os.path.isdir(tool_dir):
                continue
            jsnol = os.path.join(tool_dir, f"{name}.jsnol")
            if os.path.isfile(jsnol):
                try:
                    with open(jsnol, encoding="utf-8") as f:
                        meta = json.load(f)
                    result.append({
                        "name": name,
                        "version": meta.get("version", "?"),
                        "description": meta.get("description", ""),
                        "entry": meta.get("entry", ""),
                        "path": tool_dir,
                    })
                except Exception:
                    result.append({"name": name, "version": "?", "path": tool_dir})
            else:
                result.append({"name": name, "version": "?", "path": tool_dir})
        return result

    def discover_skills(self) -> List[Dict[str, Any]]:
        skills_dir = os.path.join(self.root, "skills")
        result = []
        if not os.path.isdir(skills_dir):
            return result
        for fname in sorted(os.listdir(skills_dir)):
            if fname.endswith(".md") and fname not in ("read.md", "README.md"):
                path = os.path.join(skills_dir, fname)
                try:
                    with open(path, encoding="utf-8") as f:
                        content = f.read()
                    version = "1.0.0"
                    for line in content.split("\n"):
                        if line.lower().startswith("version:"):
                            version = line.split(":", 1)[1].strip()
                            break
                    result.append({
                        "name": fname[:-3],
                        "version": version,
                        "path": path,
                    })
                except Exception:
                    result.append({"name": fname[:-3], "version": "?", "path": path})
        return result

    def discover_evolution_modules(self) -> List[Dict[str, Any]]:
        evo_dir = os.path.join(self.root, "evolution")
        result = []
        if not os.path.isdir(evo_dir):
            return result
        for name in sorted(os.listdir(evo_dir)):
            if name.startswith(("_", ".")) or name == "__pycache__":
                continue
            mod_dir = os.path.join(evo_dir, name)
            if not os.path.isdir(mod_dir):
                continue
            jsnol = os.path.join(mod_dir, f"{name}.jsnol")
            if os.path.isfile(jsnol):
                try:
                    with open(jsnol, encoding="utf-8") as f:
                        meta = json.load(f)
                    result.append({
                        "name": name,
                        "type": "evolution",
                        "version": meta.get("version", "?"),
                        "description": meta.get("description", ""),
                    })
                except Exception:
                    result.append({"name": name, "type": "evolution", "version": "?"})
        return result

    def discover_plugins(self) -> List[Dict[str, Any]]:
        plugins_dir = os.path.join(self.root, "plugins")
        result = []
        if not os.path.isdir(plugins_dir):
            return result
        for name in sorted(os.listdir(plugins_dir)):
            if name.startswith(("_", ".")):
                continue
            plugin_dir = os.path.join(plugins_dir, name)
            if not os.path.isdir(plugin_dir):
                continue
            jsnol = os.path.join(plugin_dir, f"{name}.jsnol")
            if os.path.isfile(jsnol):
                try:
                    with open(jsnol, encoding="utf-8") as f:
                        meta = json.load(f)
                    result.append({
                        "name": name,
                        "version": meta.get("version", "?"),
                        "description": meta.get("description", ""),
                    })
                except Exception:
                    result.append({"name": name, "version": "?"})
        return result

    def get_context_map(self) -> Dict[str, Any]:
        return {
            "tools": self.discover_tools(),
            "skills": self.discover_skills(),
            "evolution_modules": self.discover_evolution_modules(),
            "plugins": self.discover_plugins(),
            "version": "1.0.0",
        }

    def discover_all(self) -> Dict[str, Any]:
        return self.get_context_map()
