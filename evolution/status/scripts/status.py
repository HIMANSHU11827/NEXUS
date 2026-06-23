"""Evolution Status — unified dashboard across all evolution forges."""
__version__ = "1.0.0"
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional
from evolution.logs import EvolutionLog
logger = logging.getLogger(__name__)

class EvolutionStatus:
    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)

    def report(self) -> Dict[str, Any]:
        return {"skills": self._scan_skills(), "tools": self._scan_tools(), "plugins": self._scan_plugins(), "memories": self._scan_memories(), "knowledge": self._scan_knowledge(), "sops": self._scan_sops(), "ledger": self._read_ledger_summary(), "log": self._read_log_summary(), "generated_at": time.time()}

    def summary(self) -> str:
        r = self.report()
        lines = ["+" + "=" * 44 + "+", "|        NEXUS EVOLUTION STATUS         |", "+" + "=" * 44 + "+", ""]
        lines.append(f"  Skills:    {r['skills']['count']:>3}")
        for s in r["skills"]["items"]:
            lines.append(f"    |- {s['name'][:25]:<25} v{s['version']}")
        lines.append("")
        lines.append(f"  Tools:     {r['tools']['count']:>3}")
        for t in r["tools"]["items"]:
            lines.append(f"    |- {t['name'][:25]:<25} v{t['version']}")
        lines.append("")
        lines.append(f"  Plugins:   {r['plugins']['count']:>3}")
        lines.append("")
        lines.append(f"  Memories:  {r['memories']['count']:>3}")
        lines.append("")
        lines.append(f"  Knowledge: {r['knowledge']['count']:>3}")
        lines.append("")
        lines.append(f"  SOPs:      {r['sops']['count']:>3}")
        log = r.get("log", {})
        lines.append("")
        lines.append(f"  Usage Log: {log.get('total_events', 0)} events, {log.get('success_rate', 0)}% success")
        return "\n".join(lines)

    def _scan_skills(self) -> Dict:
        skills_dir = os.path.join(self.root, "skills")
        items = []
        if os.path.isdir(skills_dir):
            for cat in sorted(os.listdir(skills_dir)):
                cat_path = os.path.join(skills_dir, cat)
                if not os.path.isdir(cat_path) or cat.startswith("."):
                    continue
                for entry in sorted(os.listdir(cat_path)):
                    skill_md = os.path.join(cat_path, entry, "SKILL.md")
                    if os.path.isfile(skill_md):
                        ver = self._version_from_md(skill_md)
                        items.append({"name": f"{cat}/{entry}", "version": ver})
        return {"count": len(items), "items": items}

    def _scan_tools(self) -> Dict:
        tools_dir = os.path.join(self.root, "tools")
        items = []
        if os.path.isdir(tools_dir):
            for entry in sorted(os.listdir(tools_dir)):
                tool_dir = os.path.join(tools_dir, entry)
                if not os.path.isdir(tool_dir) or entry.startswith("_"):
                    continue
                ver = "?"
                schema_path = os.path.join(tool_dir, f"{entry}.json")
                if os.path.isfile(schema_path):
                    try:
                        with open(schema_path, "r", encoding="utf-8") as f:
                            ver = json.load(f).get("version", "?")
                    except Exception:
                        pass
                items.append({"name": entry, "version": str(ver)})
        return {"count": len(items), "items": items}

    def _scan_plugins(self) -> Dict:
        plugins_dir = os.path.join(self.root, "plugins")
        items = []
        if os.path.isdir(plugins_dir):
            for entry in sorted(os.listdir(plugins_dir)):
                pd = os.path.join(plugins_dir, entry)
                if not os.path.isdir(pd) or entry.startswith("_"):
                    continue
                ver = "?"
                for fname in os.listdir(pd):
                    if fname.endswith(".json"):
                        try:
                            with open(os.path.join(pd, fname), "r", encoding="utf-8") as f:
                                ver = json.load(f).get("version", "?")
                        except Exception:
                            pass
                items.append({"name": entry, "version": str(ver)})
        return {"count": len(items), "items": items}

    def _scan_memories(self) -> Dict:
        memory_dir = os.path.join(self.root, "memory")
        items = []
        if os.path.isdir(memory_dir):
            for entry in sorted(os.listdir(memory_dir)):
                mem_dir = os.path.join(memory_dir, entry)
                if not os.path.isdir(mem_dir):
                    continue
                for fname in os.listdir(mem_dir):
                    if fname.endswith(".json"):
                        try:
                            with open(os.path.join(mem_dir, fname), "r", encoding="utf-8") as f:
                                data = json.load(f)
                            items.append({"title": data.get("title", entry), "importance": data.get("importance", 0)})
                        except Exception:
                            pass
        return {"count": len(items), "items": items}

    def _scan_knowledge(self) -> Dict:
        lib_dir = os.path.join(self.root, "knowledge", "library")
        items = []
        if os.path.isdir(lib_dir):
            for entry in sorted(os.listdir(lib_dir)):
                topic_dir = os.path.join(lib_dir, entry)
                if not os.path.isdir(topic_dir):
                    continue
                for fname in os.listdir(topic_dir):
                    if fname.endswith(".json"):
                        try:
                            with open(os.path.join(topic_dir, fname), "r", encoding="utf-8") as f:
                                data = json.load(f)
                            items.append({"title": data.get("title", entry), "key_concepts": data.get("key_concepts", [])})
                        except Exception:
                            pass
        return {"count": len(items), "items": items}

    def _scan_sops(self) -> Dict:
        sop_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "sop")
        items = []
        if os.path.isdir(sop_dir):
            for fname in sorted(os.listdir(sop_dir)):
                if fname.endswith(".md"):
                    items.append(fname[:-3])
        return {"count": len(items), "items": [{"name": i} for i in items]}

    def _read_log_summary(self) -> Dict:
        try:
            return EvolutionLog(self.root).stats()
        except Exception:
            return {}

    def _read_ledger_summary(self) -> Dict:
        try:
            from evolution.ledger.scripts.ledger import EvolutionLedger
            s = EvolutionLedger(self.root).summary()
            return {"events": {"total": s.get("total_events", 0), "by_kind": s.get("by_kind", {}), "applied": s.get("applied", 0)}}
        except Exception:
            return {"events": {"total": 0}}

    @staticmethod
    def _version_from_md(path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            if content.startswith("---"):
                end = content.find("---", 3)
                if end > 0:
                    m = re.search(r"version:\s*([\d.]+)", content[:end])
                    if m:
                        return m.group(1)
        except Exception:
            pass
        return "?"
