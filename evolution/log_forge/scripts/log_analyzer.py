"""Log Analyzer — reads ALL logs/, finds patterns, drives evolution."""
import json
import logging
import os
import re
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple
logger = logging.getLogger(__name__)

class LogAnalyzer:
    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)
        self.logs_dir = os.path.join(self.root, "logs")
        self._router = None

    def _get_router(self):
        if self._router is None:
            try:
                from providers.router import ModelRouter
                self._router = ModelRouter()
            except Exception:
                return None
        return self._router

    def scan_logs(self) -> Dict[str, Any]:
        result = {}
        if not os.path.isdir(self.logs_dir):
            return result
        for subdir in sorted(os.listdir(self.logs_dir)):
            sub_path = os.path.join(self.logs_dir, subdir)
            if not os.path.isdir(sub_path):
                continue
            entries = []
            for fname in os.listdir(sub_path):
                if fname.endswith(".json") or fname.endswith(".jsonl"):
                    try:
                        with open(os.path.join(sub_path, fname), "r", encoding="utf-8") as f:
                            if fname.endswith(".jsonl"):
                                for line in f:
                                    if line.strip():
                                        entries.append(json.loads(line))
                            else:
                                entries.append(json.load(f))
                    except Exception:
                        pass
            if entries:
                result[subdir] = entries
        return result

    def analyze(self) -> Dict[str, Any]:
        logs = self.scan_logs()
        patterns = {"failure_patterns": [], "skill_gaps": [], "tool_opportunities": [], "memory_candidates": [], "knowledge_gaps": []}
        failures = logs.get("failures", []) + logs.get("errors", []) + logs.get("lose", [])
        if failures:
            error_msgs = [f.get("message", "") or f.get("summary", "")[:100] for f in failures[:10]]
            patterns["failure_patterns"] = error_msgs[:5]
        wins = logs.get("win", [])
        if wins:
            topics = [w.get("name", "") for w in wins if w.get("name")]
            from collections import Counter
            freq = Counter(topics)
            for topic, count in freq.most_common(3):
                patterns["skill_gaps"].append({"name": topic, "reason": f"Used successfully {count} times — consider promoting to skill"})
        return patterns

    def evolve(self) -> Dict[str, Any]:
        patterns = self.analyze()
        actions = []
        for gap in patterns.get("skill_gaps", []):
            try:
                from evolution.skill_forge.scripts.forge import SkillForge
                forge = SkillForge(self.root)
                result = forge.forge(gap["name"], gap["reason"])
                if result.get("created"):
                    actions.append({"type": "skill", "name": gap["name"], "result": "created"})
            except Exception:
                pass
        for gap in patterns.get("tool_opportunities", []):
            try:
                from evolution.tool_forge.scripts.engine import ToolForge
                forge = ToolForge(self.root)
                result = forge.forge(gap)
                if result.get("created"):
                    actions.append({"type": "tool", "name": gap.get("name", "unknown"), "result": "created"})
            except Exception:
                pass
        return {"patterns_found": len(patterns.get("failure_patterns", [])) + len(patterns.get("skill_gaps", [])), "actions_taken": len(actions), "actions": actions}
