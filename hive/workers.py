"""Hive worker adapters for role-specific agent execution."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from hive.engine import HiveTask


class HiveLLMWorker:
    """Execute Hive tasks through a role-specific LLM prompt with fallback."""

    def __init__(
        self,
        root_dir: str,
        router: Any = None,
        fallback_worker: Optional[Callable[[HiveTask, Dict[str, Any]], str]] = None,
    ) -> None:
        self.root = root_dir
        self.router = router
        self.fallback_worker = fallback_worker

    def __call__(self, task: HiveTask, context: Dict[str, Any]) -> str:
        router = self.router or self._default_router()
        messages = self.build_messages(task, context)
        try:
            result = router.generate(messages=messages, temperature=0.2)
        except Exception as exc:
            return self._fallback(task, context, f"router exception: {exc}")

        if self._looks_failed(result):
            return self._fallback(task, context, f"router failed: {result}")
        return self._normalize_result(task, str(result))

    def build_messages(self, task: HiveTask, context: Dict[str, Any]) -> List[Dict[str, str]]:
        contract = context.get("contract") or {}
        handoff = context.get("handoff") or {}
        role = contract.get("role") or task.role
        system = (
            f"You are a NEXUS Hive worker acting as {role}.\n"
            f"Persona: {contract.get('persona', 'Scoped specialist worker.')}\n"
            "Work only from the handoff, prior artifacts, and explicit mission context.\n"
            "Coordinate through hive_broadcast/hive_team when needed.\n"
            "Return concise structured output with evidence, blockers, and handoff notes.\n"
            "Do not claim code changes or tests unless the handoff/tool evidence proves them."
        )
        payload = {
            "task": {
                "id": task.id,
                "hive_id": task.hive_id,
                "role": task.role,
                "objective": task.objective,
                "constraints": task.constraints,
                "required_outputs": task.required_outputs,
            },
            "contract": contract,
            "handoff": {
                "id": handoff.get("id"),
                "prior_artifacts": handoff.get("prior_artifacts", [])[-5:],
                "short_term_memory": handoff.get("short_term_memory", [])[-8:],
                "long_term_memory": handoff.get("long_term_memory", [])[-5:],
                "failure_context": handoff.get("failure_context", [])[-5:],
            },
            "allowed_tools": contract.get("allowed_tools", []),
        }
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, indent=2, ensure_ascii=False)},
        ]

    def _default_router(self) -> Any:
        from providers.router import ModelRouter

        return ModelRouter()

    def _fallback(self, task: HiveTask, context: Dict[str, Any], reason: str) -> str:
        if self.fallback_worker:
            fallback = self.fallback_worker(task, context)
        else:
            fallback = f"{task.role} completed deterministic fallback for: {task.objective}"
        return f"[HIVE_LLM_FALLBACK]: {reason}\n{fallback}"

    @staticmethod
    def _looks_failed(result: Any) -> bool:
        if not isinstance(result, str):
            return False
        lowered = result.strip().lower()
        return not lowered or lowered.startswith("error:") or lowered.startswith("[provider_error]")

    @staticmethod
    def _normalize_result(task: HiveTask, result: str) -> str:
        if task.role in result[:200]:
            return result
        return f"[{task.role}]\n{result}"
