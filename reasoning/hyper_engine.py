"""Planner / critic / verifier reasoning engine.

Two modes:

1. **LLM-backed (real reasoning)** — when an ``llm_call`` callable or a provider
   is supplied, ``plan``/``critique``/``verify`` issue genuine LLM calls with
   structured prompts and parse the model's chain-of-thought into typed objects.
2. **Deterministic fallback** — when no LLM is available (or any LLM call
   fails), the original keyword/heuristic scaffolding is used so the engine
   never crashes and always returns a usable plan.

Both sync and async entry points exist (``plan`` / ``aplan`` etc.). The sync
entry points transparently drive async ``llm_call``s.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ReasoningStep:
    id: str
    objective: str
    suggested_tool: str
    risk: str = "low"
    verifier: str = ""
    status: str = "planned"


@dataclass
class VerificationResult:
    passed: bool
    reason: str = ""
    source: str = "deterministic"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def __bool__(self) -> bool:  # pragma: no cover - trivial
        return bool(self.passed)


@dataclass
class ReasoningPlan:
    task: str
    steps: List[ReasoningStep] = field(default_factory=list)
    uncertainty: float = 0.0
    critiques: List[str] = field(default_factory=list)
    # Set from the critic's parsed ``should_replan`` signal so callers can
    # act on it; without this the signal is parsed and then discarded.
    should_replan: bool = False
    rationale: str = ""
    source: str = "deterministic"

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["steps"] = [asdict(step) for step in self.steps]
        return data

    def to_text(self) -> str:
        lines = [f"Plan[{self.source}] for: {self.task}"]
        if self.rationale:
            lines.append(f"Rationale: {self.rationale}")
        for i, step in enumerate(self.steps, 1):
            lines.append(
                f"{i}. [{step.id}] {step.objective} (tool={step.suggested_tool}, "
                f"risk={step.risk}, verify={step.verifier})"
            )
        lines.append(f"Uncertainty: {self.uncertainty:.2f}")
        for c in self.critiques:
            lines.append(f"Critique: {c}")
        return "\n".join(lines)

    def __str__(self) -> str:
        return self.to_text()

    def __getitem__(self, item):
        """Slicing/indexing yields the rendered plan text (ergonomic for logs)."""
        if isinstance(item, (int, slice)):
            return self.to_text()[item]
        raise TypeError(f"Unsupported index type: {type(item)!r}")

    def __len__(self) -> int:
        return len(self.to_text())


PLANNER_SYSTEM = (
    "You are a meticulous software-engineering planner. Given a task, produce a "
    "short, concrete, verifiable plan. Respond with STRICT JSON only, no prose:\n"
    '{"rationale": "<2-3 sentence chain of thought>", "steps": ['
    '{"id": "short_id", "objective": "...", "suggested_tool": "repo_map|grep|read|file_edit|bash|final", '
    '"risk": "low|medium|high", "verifier": "how to confirm this step succeeded"}]}'
    "\nUse 3-7 steps. The last step must summarize with evidence."
)

CRITIC_SYSTEM = (
    "You are a ruthless plan critic. Find real flaws: missing verification, unsafe "
    "steps, wrong assumptions, scope creep, missing rollback. Respond with STRICT JSON only:\n"
    '{"critiques": ["..."], "should_replan": true|false, "confidence": 0.0-1.0}'
    "\nReturn an empty critiques list if the plan is genuinely sound."
)

VERIFIER_SYSTEM = (
    "You are a strict verifier. Decide whether the RESULT actually satisfies the TASK. "
    "Respond with STRICT JSON only:\n"
    '{"passed": true|false, "reason": "<one or two sentences of evidence-based judgement>"}'
)


def _extract_json(text: str) -> Optional[Any]:
    """Best-effort JSON extraction from an LLM response."""
    if not text:
        return None
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.S)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        end = cleaned.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except Exception:
                continue
    return None


def _run_coroutine_blocking(coro):
    """Run a coroutine from sync code, even inside a running event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: Dict[str, Any] = {}

    def _runner():
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001
            result["error"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


class HyperReasoningEngine:
    """Creates explicit, verifiable plans — LLM-backed when possible."""

    def __init__(
        self,
        llm_call: Optional[Callable[[str, str], Any]] = None,
        provider: Any = None,
        model: Optional[str] = None,
        enable_llm: bool = True,
        max_tokens: int = 900,
        use_default_provider: bool = False,
    ) -> None:
        self.llm_call = llm_call
        self.model = model
        self.max_tokens = max_tokens
        self.enable_llm = enable_llm
        # Auto-resolving the configured cloud provider is opt-in so a bare
        # HyperReasoningEngine() stays offline, fast and fully deterministic.
        self.use_default_provider = bool(use_default_provider or isinstance(provider, str))
        self._provider = None
        self._provider_spec = provider
        self.last_error: Optional[str] = None
        if provider is not None and not isinstance(provider, str):
            self._provider = provider

    # ------------------------------------------------------------------ LLM

    def _resolve_provider(self) -> Any:
        if self._provider is not None:
            return self._provider
        if not self.enable_llm or not self.use_default_provider:
            return None
        try:
            from providers.factory import NexusProviderFactory

            factory = NexusProviderFactory()
            if isinstance(self._provider_spec, str) and self._provider_spec:
                self._provider = factory.get_provider_by_id(self._provider_spec)
            else:
                self._provider = factory.get_provider()
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"provider init failed: {exc}"
            logger.debug("HyperReasoningEngine: %s", self.last_error)
            self._provider = None
        return self._provider

    @property
    def llm_available(self) -> bool:
        if not self.enable_llm:
            return False
        if self.llm_call is not None:
            return True
        return self._resolve_provider() is not None

    async def _ainvoke(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        if not self.enable_llm:
            return None
        if self.llm_call is not None:
            try:
                out = self.llm_call(system_prompt, user_prompt)
                if asyncio.iscoroutine(out):
                    out = await out
                return str(out) if out else None
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"llm_call failed: {exc}"
                logger.debug("HyperReasoningEngine: %s", self.last_error)
                return None

        provider = self._resolve_provider()
        if provider is None:
            return None
        try:
            kwargs: Dict[str, Any] = {}
            if self.model:
                kwargs["model"] = self.model
            out = await asyncio.to_thread(
                provider.generate, user_prompt, system_prompt, None, **kwargs
            )
            return str(out) if out else None
        except TypeError:
            try:
                out = await asyncio.to_thread(
                    provider.generate, prompt=user_prompt, system_prompt=system_prompt
                )
                return str(out) if out else None
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"provider.generate failed: {exc}"
                return None
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"provider.generate failed: {exc}"
            logger.debug("HyperReasoningEngine: %s", self.last_error)
            return None

    def _invoke(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        if not self.enable_llm:
            return None
        try:
            return _run_coroutine_blocking(self._ainvoke(system_prompt, user_prompt))
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"sync llm invoke failed: {exc}"
            return None

    # ----------------------------------------------------------------- plan

    def plan(self, task: str, context: str = "") -> ReasoningPlan:
        self._last_critic_signal = None
        raw = self._invoke(PLANNER_SYSTEM, self._plan_prompt(task, context))
        plan = self._plan_from_llm(task, raw)
        if plan is None:
            plan = self._deterministic_plan(task)
        # Compute uncertainty BEFORE critique so _deterministic_critique can use it.
        plan.uncertainty = self.estimate_uncertainty(task, plan.steps, [])
        plan.critiques = self.critique(plan)
        self._apply_critic_signal(plan, task)
        return plan

    async def aplan(self, task: str, context: str = "") -> ReasoningPlan:
        self._last_critic_signal = None
        raw = await self._ainvoke(PLANNER_SYSTEM, self._plan_prompt(task, context))
        plan = self._plan_from_llm(task, raw) or self._deterministic_plan(task)
        plan.uncertainty = self.estimate_uncertainty(task, plan.steps, [])
        plan.critiques = await self.acritique(plan)
        self._apply_critic_signal(plan, task)
        return plan

    def _apply_critic_signal(self, plan: ReasoningPlan, task: str) -> None:
        """Fold the critic's real output back into the plan.

        The critic's ``critiques`` list and its parsed ``should_replan`` /
        ``confidence`` signal were previously computed after the only
        ``estimate_uncertainty`` call, so neither ever influenced the plan
        returned to callers. Re-scoring here is the read side of that
        already-stored state; it never raises.
        """
        try:
            signal = getattr(self, "_last_critic_signal", None)
            plan.should_replan = bool(
                isinstance(signal, dict) and signal.get("should_replan")
            )
            plan.uncertainty = self.estimate_uncertainty(
                task, plan.steps, plan.critiques
            )
        except Exception:  # noqa: BLE001 - scoring must never break planning
            logger.debug("HyperReasoningEngine: critic signal apply failed", exc_info=True)

    @staticmethod
    def _plan_prompt(task: str, context: str = "") -> str:
        prompt = f"TASK:\n{task}"
        if context:
            prompt += f"\n\nCONTEXT:\n{context}"
        return prompt

    def _plan_from_llm(self, task: str, raw: Optional[str]) -> Optional[ReasoningPlan]:
        data = _extract_json(raw) if raw else None
        if not isinstance(data, dict):
            return None
        raw_steps = data.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            return None
        steps: List[ReasoningStep] = []
        for i, item in enumerate(raw_steps, 1):
            if not isinstance(item, dict):
                continue
            objective = str(item.get("objective") or item.get("description") or "").strip()
            if not objective:
                continue
            steps.append(
                ReasoningStep(
                    id=str(item.get("id") or f"step_{i}")[:48],
                    objective=objective,
                    suggested_tool=str(item.get("suggested_tool") or item.get("tool") or "bash"),
                    risk=str(item.get("risk") or "low").lower(),
                    verifier=str(item.get("verifier") or ""),
                )
            )
        if not steps:
            return None
        return ReasoningPlan(
            task=task,
            steps=steps,
            rationale=str(data.get("rationale") or "").strip(),
            source="llm",
        )

    def _deterministic_plan(self, task: str) -> ReasoningPlan:
        task_l = task.lower()
        steps: List[ReasoningStep] = [
            ReasoningStep("understand", "Map relevant files and existing behavior", "repo_map", verifier="source files identified")
        ]
        if any(k in task_l for k in ["bug", "debug", "crash", "fail", "fix"]):
            steps.append(ReasoningStep("reproduce", "Reproduce or inspect the failure", "bash", risk="medium", verifier="failure observed or logs inspected"))
        if any(k in task_l for k in ["implement", "fix", "refactor", "add", "code"]):
            steps.append(ReasoningStep("edit", "Apply the smallest coherent code change", "file_edit", risk="medium", verifier="syntax check passes"))
        if any(k in task_l for k in ["security", "upload", "auth", "api"]):
            steps.append(ReasoningStep("security", "Check API/path/auth/security boundaries", "grep", verifier="risk cases covered"))
        steps.append(ReasoningStep("verify", "Run targeted tests/builds", "bash", verifier="tests/build pass"))
        steps.append(ReasoningStep("summarize", "Summarize changes, remaining risks, and evidence", "final", verifier="evidence cited"))
        return ReasoningPlan(task=task, steps=steps, source="deterministic")

    # -------------------------------------------------------------- critique

    def critique(self, plan: ReasoningPlan, observation: str = "") -> List[str]:
        raw = self._invoke(CRITIC_SYSTEM, self._critique_prompt(plan, observation))
        parsed = self._critique_from_llm(raw)
        if parsed is None:
            return self._deterministic_critique(plan, observation)
        self._last_critic_signal = parsed
        return parsed.get("critiques", [])

    async def acritique(self, plan: ReasoningPlan, observation: str = "") -> List[str]:
        raw = await self._ainvoke(CRITIC_SYSTEM, self._critique_prompt(plan, observation))
        parsed = self._critique_from_llm(raw)
        if parsed is None:
            return self._deterministic_critique(plan, observation)
        self._last_critic_signal = parsed
        return parsed.get("critiques", [])

    @staticmethod
    def _critique_prompt(plan: ReasoningPlan, observation: str = "") -> str:
        prompt = f"PLAN:\n{plan.to_text()}"
        if observation:
            prompt += f"\n\nLATEST OBSERVATION:\n{observation[:4000]}"
        return prompt

    def _critique_from_llm(self, raw: Optional[str]) -> Optional[Dict[str, Any]]:
        data = _extract_json(raw) if raw else None
        if isinstance(data, list):
            data = {"critiques": data}
        if not isinstance(data, dict):
            return None
        critiques = data.get("critiques")
        if not isinstance(critiques, list):
            return None
        out = {
            "critiques": [str(c).strip() for c in critiques if str(c).strip()],
            "should_replan": bool(data.get("should_replan", False)),
            "confidence": float(data.get("confidence", 0.5) or 0.5),
        }
        return out

    def _deterministic_critique(self, plan: ReasoningPlan, observation: str = "") -> List[str]:
        critiques: List[str] = []
        if plan.uncertainty > 0.6:
            critiques.append("High uncertainty: narrow scope or gather more repo evidence before broad edits.")
        if not any(step.suggested_tool == "bash" for step in plan.steps):
            critiques.append("No execution verification step found.")
        if any(step.risk in {"high", "critical"} for step in plan.steps):
            critiques.append("High-risk step requires rollback/snapshot planning.")
        if observation and re.search(r"traceback|error|failed", observation.lower()):
            critiques.append("Observation contains failure signals: re-examine assumptions.")
        return critiques

    # ---------------------------------------------------------------- verify

    def verify(self, task: str, result: str) -> VerificationResult:
        raw = self._invoke(VERIFIER_SYSTEM, self._verify_prompt(task, result))
        parsed = self._verify_from_llm(raw)
        return parsed or self._deterministic_verify(task, result)

    async def averify(self, task: str, result: str) -> VerificationResult:
        raw = await self._ainvoke(VERIFIER_SYSTEM, self._verify_prompt(task, result))
        parsed = self._verify_from_llm(raw)
        return parsed or self._deterministic_verify(task, result)

    @staticmethod
    def _verify_prompt(task: str, result: str) -> str:
        return f"TASK:\n{task}\n\nRESULT:\n{str(result)[:6000]}"

    def _verify_from_llm(self, raw: Optional[str]) -> Optional[VerificationResult]:
        data = _extract_json(raw) if raw else None
        if not isinstance(data, dict) or "passed" not in data:
            return None
        return VerificationResult(
            passed=bool(data.get("passed")),
            reason=str(data.get("reason") or "").strip(),
            source="llm",
        )

    @staticmethod
    def _deterministic_verify(task: str, result: str) -> VerificationResult:
        text = str(result or "")
        low = text.lower()
        if not text.strip():
            return VerificationResult(False, "Empty result — nothing to verify.")
        for marker in ("traceback", "error:", "failed", "exception", "permission denied"):
            if marker in low:
                return VerificationResult(False, f"Result contains failure marker: '{marker}'.")
        return VerificationResult(True, "No failure markers detected in result (heuristic check).")

    # ----------------------------------------------------------- uncertainty

    def estimate_uncertainty(
        self,
        task: str,
        steps: List[ReasoningStep],
        critiques: Optional[List[str]] = None,
    ) -> float:
        uncertainty = 0.2
        if len(task) < 25:
            uncertainty += 0.25
        if re.search(r"\b(all|everything|entire|massive|production-grade)\b", task.lower()):
            uncertainty += 0.25
        if len(steps) > 5:
            uncertainty += 0.1
        if critiques:
            uncertainty += min(0.3, 0.1 * len(critiques))
        signal = getattr(self, "_last_critic_signal", None)
        if isinstance(signal, dict):
            confidence = signal.get("confidence")
            if isinstance(confidence, (int, float)):
                uncertainty = max(uncertainty, 1.0 - float(confidence))
            if signal.get("should_replan"):
                uncertainty += 0.1
        return round(min(0.95, max(0.0, uncertainty)), 3)

    # ------------------------------------------------------------- replan

    def should_replan(self, plan: ReasoningPlan, observations: Any) -> bool:
        obs_list = [observations] if isinstance(observations, str) else list(observations or [])
        joined = "\n".join(str(o) for o in obs_list).lower()
        if any(m in joined for m in ["traceback", "failed", "error", "timeout", "permission denied"]):
            return True
        if joined.strip() and self.llm_available:
            raw = self._invoke(CRITIC_SYSTEM, self._critique_prompt(plan, joined))
            parsed = self._critique_from_llm(raw)
            if parsed is not None:
                self._last_critic_signal = parsed
                if parsed.get("should_replan"):
                    return True
        completed = sum(1 for step in plan.steps if step.status == "done")
        return completed == 0 and len(obs_list) > 2
