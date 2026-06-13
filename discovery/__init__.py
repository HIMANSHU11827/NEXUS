import os
import json
import time
from typing import List, Dict, Any, Optional


class NexusAutoDiscover:
    """
    NEXUS auto-discovery.
    Deep repository grounding and dynamic capability mapping.
    """

    root: str
    _cached_map: Optional[str]
    _last_scan: float

    def __init__(self, root_dir: str = ".") -> None:
        self.root = os.path.abspath(root_dir)
        self._cached_map = None
        self._last_scan = 0.0

    def discover_skills(self) -> List[Dict[str, str]]:
        """⚡ 3.5: DEEP-SKILL INJECTION (Real NLU Reading)"""
        skills = []

        # Native skills - Read actual content brief
        skill_path = os.path.join(self.root, "skill")
        if os.path.exists(skill_path):
            for f in os.listdir(skill_path):
                if f.endswith(".md"):
                    name = f.replace(".md", "")
                    content_brief = ""
                    try:
                        with open(
                            os.path.join(skill_path, f), "r", encoding="utf-8"
                        ) as f_obj:
                            first_lines = "".join(f_obj.readlines()[:5])
                            content_brief = first_lines[:150].strip().replace("\n", " ")
                    except (OSError, IOError):
                        pass
                    skills.append({"id": name, "type": "nexus", "brief": content_brief})

        # Plugin-provided skills live in the top-level plugins directory.
        plugin_skills_path = os.path.join(self.root, "plugins")
        if os.path.exists(plugin_skills_path):
            for skill_dir in os.listdir(plugin_skills_path):
                full_dir = os.path.join(plugin_skills_path, skill_dir)
                if os.path.isdir(full_dir):
                    skill_md = os.path.join(full_dir, "SKILL.md")
                    if os.path.exists(skill_md):
                        summary = "Active skill."
                        try:
                            with open(skill_md, "r", encoding="utf-8") as f_obj:
                                summary = f_obj.read(150).strip().replace("\n", " ")
                        except (OSError, IOError):
                            pass
                        skills.append({"id": f"plugin:{skill_dir}", "summary": summary})

        return skills

    def discover_tools(self) -> List[Dict[str, Any]]:
        """Return the real executable tool surface.

        Older NEXUS builds scanned every `tools/*/script.py` folder. That made
        abandoned experimental folders appear active even when the runtime never
        registered them. Discovery now mirrors `ToolRegistry`, which is the
        actual execution boundary.
        """
        try:
            from tools.nexus_tools.registry import ToolRegistry

            registry = ToolRegistry()
            names = set(registry.list_tools())
            if not {"bash", "file_edit", "grep", "glob"}.issubset(names):
                ToolRegistry._reset_instance()
                ToolRegistry._initialized = False
                registry = ToolRegistry()

            return [
                {
                    "name": schema.get("name", ""),
                    "description": schema.get("description", ""),
                    "source": "registry",
                }
                for schema in registry.list_all()
                if schema.get("name")
            ]
        except Exception:
            return self._discover_legacy_manifests()

    def _discover_legacy_manifests(self) -> List[Dict[str, Any]]:
        """Best-effort fallback metadata only; not an execution claim."""
        tools_list = []
        tool_path = os.path.join(self.root, "tools")
        excluded = {"terminal", "file_ops", "tester", "git", "docker", "elite", "__pycache__"}
        if not os.path.exists(tool_path):
            return tools_list
        for item in os.listdir(tool_path):
            if item in excluded:
                continue
            full_path = os.path.join(tool_path, item)
            manifest_path = os.path.join(full_path, "manifest.json")
            if os.path.isdir(full_path) and os.path.exists(manifest_path):
                manifest = {"name": item, "description": "No description.", "source": "legacy_manifest"}
                try:
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        manifest.update(json.load(f))
                except (json.JSONDecodeError, ValueError, OSError, IOError):
                    pass
                tools_list.append(manifest)
        return tools_list

    def get_action_keywords(self) -> List[str]:
        """Returns a list of action keyword strings derived from discovered skills and tools."""
        skills = self.discover_skills()
        tools = self.discover_tools()
        return [skill["id"] for skill in skills] + [tool["name"] for tool in tools]

    def get_repo_status(self) -> str:
        """Returns the high-level status of the repository grounding."""
        # Check for RAG index
        knowledge_dir = os.path.join(self.root, "knowledge")
        rag_status = "UNINDEXED"
        if os.path.isdir(knowledge_dir):
            rag_status = "READY" if any(
                name.startswith("_rag_index_") and name.endswith(".json")
                for name in os.listdir(knowledge_dir)
            ) else "UNINDEXED"

        # Check for manifest
        nexus_manifest = os.path.join(self.root, "manifest.json")
        nexus_status = "ACTIVE" if os.path.exists(nexus_manifest) else "MISSING"

        return f"RAG-Store={rag_status} | Manifest={nexus_status}"

    def get_context_map(self) -> str:
        """Returns a deep-grounded map for the Super Prompt (v3.5)."""
        import time

        if self._cached_map and (time.time() - self._last_scan) < 30.0:
            return self._cached_map

        skills = self.discover_skills()
        tools = self.discover_tools()
        repo = self.get_repo_status()

        # 🦾 3.5: Multi-Capability Mapping
        skills_lines = []
        for s in skills:
            brief = s.get("brief", s.get("summary", "No summary."))
            skills_lines.append(f"- {s['id']}: {brief}")

        skills_str = "\n".join(skills_lines)
        tools_str = ", ".join([t["name"] for t in tools])

        # ⚡ Load Master Instructions (Real NLU)
        master_instr = "None."
        instr_path = os.path.join(self.root, "skill", "instructions.md")
        if os.path.exists(instr_path):
            try:
                with open(instr_path, "r", encoding="utf-8") as f:
                    master_instr = f.read()
            except (OSError, IOError):
                pass

        self._cached_map = (
            f"# REPO GROUNDING: [{repo}]\n"
            f"# MASTER DIRECTIVES:\n{master_instr}\n"
            f"# DISCOVERED CAPABILITIES:\n{skills_str}\n"
            f"# ACTIVE TOOLS: [{tools_str}]"
        )
        self._last_scan = time.time()
        return self._cached_map


if __name__ == "__main__":
    d = NexusAutoDiscover()
    print(d.get_context_map())
