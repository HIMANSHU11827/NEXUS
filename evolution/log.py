"""Evolution Log — bridges evolution system with the logs/ directory."""
import json
import logging
import os
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)
LOG_DIR = "logs"
ENTITY_TYPES = ("skill", "tool", "plugin", "memory", "knowledge", "test", "sop", "agent", "config")
_LOG_MAP = {
    "win": LOG_DIR + "/win",
    "lose": LOG_DIR + "/lose",
    "failure": LOG_DIR + "/failures",
    "experience": LOG_DIR + "/experience",
    "error": LOG_DIR + "/errors",
    "improvement": LOG_DIR + "/improvements",
}
_ENTITY_LOG_MAP = {"skill": LOG_DIR + "/skills", "tool": LOG_DIR + "/tools", "plugin": LOG_DIR + "/plugins"}

class EvolutionLog:
    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)
        self.evolution_log = os.path.join(self.root, LOG_DIR, "evolution", "evolution_log.jsonl")
        self._init_dirs()

    def _init_dirs(self):
        for d in set(list(_LOG_MAP.values()) + list(_ENTITY_LOG_MAP.values()) + [os.path.dirname(self.evolution_log)]):
            os.makedirs(d, exist_ok=True)

    def _write(self, subdir: str, entry: Dict[str, Any]):
        path = os.path.join(self.root, subdir, f"{int(time.time())}.json")
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(entry, f)
        except Exception as e:
            logger.debug(f"Log write failed to {path}: {e}")
        try:
            os.makedirs(os.path.dirname(self.evolution_log), exist_ok=True)
            with open(self.evolution_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.debug(f"Evolution log append failed: {e}")

    def win(self, entity_type: str, name: str, summary: str, duration: float = 0.0, metadata: Dict = None) -> Dict[str, Any]:
        entry = {"outcome": "win", "entity_type": entity_type, "name": name, "summary": summary, "duration": duration, "metadata": metadata or {}, "timestamp": time.time()}
        self._write(_LOG_MAP["win"], entry)
        return entry

    def lose(self, entity_type: str, name: str, summary: str, duration: float = 0.0, metadata: Dict = None) -> Dict[str, Any]:
        entry = {"outcome": "lose", "entity_type": entity_type, "name": name, "summary": summary, "duration": duration, "metadata": metadata or {}, "timestamp": time.time()}
        self._write(_LOG_MAP["lose"], entry)
        return entry

    def error(self, component: str, message: str, details: str = "", metadata: Dict = None) -> Dict[str, Any]:
        entry = {"component": component, "message": message, "details": details, "metadata": metadata or {}, "timestamp": time.time()}
        self._write(_LOG_MAP["error"], entry)
        return entry

    def improvement(self, action: str, detail: str = "", metadata: Dict = None) -> Dict[str, Any]:
        entry = {"action": action, "detail": detail, "metadata": metadata or {}, "timestamp": time.time()}
        self._write(_LOG_MAP["improvement"], entry)
        return entry

    def experience(self, summary: str, insight: str = "", tags: List[str] = None) -> Dict[str, Any]:
        entry = {"summary": summary, "insight": insight, "tags": tags or [], "timestamp": time.time()}
        self._write(_LOG_MAP["experience"], entry)
        return entry

    def stats(self) -> Dict[str, Any]:
        by_entity = defaultdict(lambda: {"created": 0, "updated": 0, "used": 0, "unique_names": set()})
        total_events = 0
        for subdir_key, subdir_path in _LOG_MAP.items():
            full = os.path.join(self.root, subdir_path)
            if os.path.isdir(full):
                for fname in os.listdir(full):
                    if fname.endswith(".json"):
                        total_events += 1
        for ent_type, ent_path in _ENTITY_LOG_MAP.items():
            full = os.path.join(self.root, ent_path)
            if os.path.isdir(full):
                for fname in os.listdir(full):
                    if fname.endswith(".json"):
                        total_events += 1
        result = {"total_events": total_events, "total_time_hours": 0, "success_rate": 100, "by_entity": {}}
        for ent, data in by_entity.items():
            result["by_entity"][ent] = {k: (len(v) if isinstance(v, set) else v) for k, v in data.items()}
        return result
