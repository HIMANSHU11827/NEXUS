"""V5Compat — V1 subsystem integration for the V5 loop.

- NATE init with tool schema registration
- MCP server auto-connection, compiler check
- Soul file seeding, profile loading, prompt files
- Evolution hooks, file scanning with threat detection

Mixed into NexusLoopV5; every method degrades gracefully.
"""

from __future__ import annotations

import json, logging, os, re, time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class V5Compat:
    """Mixin integrating V1 subsystems."""

    def _init_nate(self) -> None:
        if getattr(self, "_nate", None) is not None:
            return
        try:
            from intelligence.nate.nate_engine import NATE
        except ImportError as e:
            logger.warning("NATE disabled: %s", e)
            self._nate = None
            return
        self._nate = NATE()
        try:
            registry = getattr(self, "tool_registry", None)
            if registry is None:
                return
            tools = registry.list_tools(include_unavailable=False)
            for name in tools:
                entry = registry.get(name)
                if not entry or not entry.schema:
                    continue
                meta = entry.schema
                pm = meta.get("params", {})
                ps = {k: {"type": v.get("type", "string"),
                          "description": str(v.get("description", ""))[:160]}
                      for k, v in pm.items()}
                req = [k for k, v in pm.items() if v.get("required")]
                schema = {"type": "function", "function": {
                    "name": name,
                    "description": str(meta.get("description", ""))[:240],
                    "parameters": {"type": "object", "properties": ps, "required": req},
                }}
                try:
                    self._nate.register_tool(name, schema)
                except Exception:
                    pass
            self.logger.info("NATE initialized with %d tools", len(tools))
        except Exception as e:
            self.logger.warning("NATE tool reg failed: %s", e)

    def nate_report(self) -> str:
        self._init_nate()
        if self._nate is None:
            return "NATE: not initialized"
        try:
            s = self._nate.stats()
            return (f"NATE: {s['tools_registered']} tools | "
                    f"{s['total_calls']} calls | "
                    f"{s['schema']['savings_percent']}% saved")
        except Exception:
            return "NATE: stats unavailable"

    def _init_mcp_servers(self) -> None:
        """Expose clients already discovered by the canonical ToolRegistry.

        Older V5 code imported ``connect_mcp_tools`` from ``mcp.client``;
        that API no longer exists.  ToolRegistry owns configured MCP startup,
        schema normalization, and collision handling, so V5 should consume
        those registry entries instead of creating a second routing path.
        """
        clients = []
        try:
            registry = getattr(self, "tool_registry", None)
            for name in registry.list_tools(include_unavailable=False) if registry else []:
                entry = registry.get(name)
                schema = getattr(entry, "schema", {}) or {}
                if schema.get("category") != "mcp":
                    continue
                client = getattr(getattr(entry, "instance", None), "_client", None)
                if client is not None and client not in clients:
                    clients.append(client)
        except Exception as e:
            self.logger.warning("MCP registry inspection failed: %s", e)
        self._mcp_clients = clients
        if clients:
            self.logger.info("Connected %d MCP server(s) via ToolRegistry", len(clients))

    def _check_compiler_status(self) -> None:
        try:
            from utils.engine_manager import STATUS_PATH
            if not os.path.exists(STATUS_PATH):
                from utils.engine_compiler import compile_llama_cpp
                compile_llama_cpp()
        except Exception:
            pass

    def _ensure_soul_file(self) -> None:
        try:
            p = os.path.join(self.root_dir, "docs", "NEXUS.md")
            if not os.path.exists(p):
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w", encoding="utf-8") as f:
                    f.write("# NEXUS Identity & Soul\n\n## Who Is NEXUS\nNEXUS is a sovereign autonomous agent.\n"
                            "## My Purpose\nAssist with tasks and creative work.\n")
        except Exception:
            pass

    def _load_soul_md(self) -> str:
        p = os.path.join(self.root_dir, "docs", "NEXUS.md")
        try:
            if os.path.isfile(p):
                with open(p, "r", encoding="utf-8") as f:
                    return f.read()[:4000]
        except Exception:
            pass
        try:
            from .core import DEFAULT_AGENT_IDENTITY
            return DEFAULT_AGENT_IDENTITY
        except Exception:
            return ""


    def _load_nexus_profile(self, detail: str = "rules") -> str:
        cache = getattr(self, "_nexus_profile_cache", None)
        if cache is None:
            self._nexus_profile_cache: Dict[str, str] = {}
        if detail in self._nexus_profile_cache:
            return self._nexus_profile_cache[detail]
        nexus_path = os.path.join(self.root_dir, "docs", "NEXUS.md")
        try:
            with open(nexus_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception:
            return ""
        sections: Dict[str, List[str]] = {}
        current = ""
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("## "):
                current = line[3:].strip()
                sections.setdefault(current, [])
                continue
            if current:
                sections.setdefault(current, []).append(line)
        wanted = ["Who Is NEXUS", "Who Is Himanshu", "My Identity",
                  "My Purpose", "How I Act", "My Ethics"]
        if detail == "identity":
            wanted = ["Who Is NEXUS", "Who Is Himanshu", "My Identity"]
        lines: List[str] = []
        for name in wanted:
            items = sections.get(name, [])
            if not items:
                continue
            cleaned = []
            for item in items:
                text = re.sub(r"^[\-\*\d\.\[\]xX\s]+", "", item).strip()
                if text:
                    cleaned.append(text)
                if len(" ".join(cleaned)) >= 260:
                    break
            if cleaned:
                lines.append(f"{name}: {' '.join(cleaned)[:260].strip()}")
        result = "\n".join(lines)
        self._nexus_profile_cache[detail] = result
        return result

    def _load_prompt_files(self) -> str:
        prompt_dirs = [os.path.join(self.root_dir, ".opencode", "prompts"),
                       os.path.join(self.root_dir, ".cursor", "rules")]
        prompt_files = [os.path.join(self.root_dir, name)
                        for name in ("AGENTS.md", "CLAUDE.md", ".cursorrules")]
        parts: List[str] = []
        candidates = list(prompt_files)
        for prompt_dir in prompt_dirs:
            if os.path.isdir(prompt_dir):
                candidates.extend(os.path.join(prompt_dir, fname)
                                  for fname in sorted(os.listdir(prompt_dir))
                                  if fname.endswith((".md", ".txt", ".mdc")))
        for fpath in candidates:
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    parts.append(f"## {os.path.basename(fpath)}\n\n{content}")
            except OSError:
                pass
        return "\n\n".join(parts)

    def _handle_evolution_gaps(self, tool_calls: Any, observations: Any) -> None:
        try:
            from evolution.curator.scripts.curator import SkillCurator
            curator = SkillCurator(self.root_dir)
            if hasattr(curator, "enabled") and curator.enabled:
                last = getattr(self, "_curator_last_run", 0)
                if last == 0 or time.time() - last >= 3600:
                    curator.run_once()
                    self._curator_last_run = time.time()
        except Exception:
            pass

    def _scan_file_safe(self, filepath: str, scope: str = "context") -> str:
        if not os.path.isfile(filepath):
            return ""
        if not getattr(self, "_threat_scan_enabled", False):
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    return f.read()
            except Exception:
                return ""
        try:
            from tools.threat_patterns import scan_file
            result = scan_file(filepath, scope=scope)
            if result.blocked or any(t.scope == "all" for t in result.threats):
                self.logger.error("[SECURITY] BLOCKED file: %s", filepath)
                return ""
        except Exception:
            pass
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception:
            return ""

    def _scan_content_safe(self, text: str) -> str:
        if not text or not getattr(self, "_threat_scan_enabled", False):
            return text or ""
        try:
            from tools.threat_patterns import scan_content
            if scan_content(text).blocked:
                return ""
        except Exception:
            pass
        return text
