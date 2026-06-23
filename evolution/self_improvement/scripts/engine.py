"""Self-Improvement Engine for NEXUS."""
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional
from providers.router import ModelRouter
logger = logging.getLogger(__name__)
_ROUTER: Optional[ModelRouter] = None

def _get_router() -> ModelRouter:
    global _ROUTER
    if _ROUTER is None:
        _ROUTER = ModelRouter()
    return _ROUTER

@dataclass
class ImprovementRecord:
    session_id: str = ""
    summary: str = ""
    actions: List[str] = field(default_factory=list)
    score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

class SelfImprovementEngine:
    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)
        self.log_path = os.path.join(self.root, "logs", "improvements", "self_improvement.jsonl")
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)

    def analyze_session(self, messages: List[Dict[str, str]]) -> Optional[ImprovementRecord]:
        try:
            router = _get_router()
            history = "\n".join([f"{m['role']}: {m['content'][:100]}" for m in messages[-10:]])
            prompt = f"""[SELF_IMPROVEMENT_ANALYSIS]
Analyze this conversation and suggest improvements:

{history}

Return JSON with:
  - summary: str (key observation)
  - actions: list[str] (specific improvements to make)
  - score: float (0-1, how much improvement potential)
"""
            result = router.generate(messages=[{"role": "user", "content": prompt}])
            try:
                data = json.loads(result)
            except Exception:
                data = {"summary": result[:200], "actions": [], "score": 0.5}
            record = ImprovementRecord(summary=data.get("summary", ""), actions=data.get("actions", []), score=data.get("score", 0.5))
            self._log(record)
            return record
        except Exception as e:
            logger.debug(f"Session analysis failed: {e}")
            return None

    def self_review(self) -> Optional[ImprovementRecord]:
        try:
            router = _get_router()
            prompt = "[SELF_REVIEW]\nReview your recent performance. What patterns do you see? What should you improve? Return JSON with summary, actions, score."
            result = router.generate(messages=[{"role": "user", "content": prompt}])
            try:
                data = json.loads(result)
            except Exception:
                data = {"summary": result[:200], "actions": [], "score": 0.5}
            record = ImprovementRecord(summary=data.get("summary", ""), actions=data.get("actions", []), score=data.get("score", 0.5))
            self._log(record)
            return record
        except Exception as e:
            logger.debug(f"Self-review failed: {e}")
            return None

    def _log(self, record: ImprovementRecord):
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(record)) + "\n")
        except Exception:
            pass
