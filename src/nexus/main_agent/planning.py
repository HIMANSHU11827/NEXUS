"""V5 Planner - Real LLM planning for the V5 loop.

Extracted from ``core.py`` and upgraded to unified-loop parity:
- Tool SCHEMAS (NATE warm lookup first, then a registry scan in OpenAI
  function format - exactly like ``loop._get_fast_tool_schemas``) are fed to
  the model so plans use valid tool names and parameter shapes.
- When the model replies without JSON, free-text tool calls are extracted
  (``name({...})``, ``<function: ...>``, dotted) and turned into plan steps.
- Parsed plan steps whose tool is unknown are dropped with a warning (only
  when the registry is available), so the PAORR loop never executes a
  misspelled tool name.
"""

from __future__ import annotations

import inspect
import json
import re
from types import SimpleNamespace
from typing import Any, Dict, List, Optional


class V5Planner:
    """Mixin providing LLM-driven plan generation."""

    # ────────────────────────────────────────────────────────────────────────
    # SCHEMAS (V5: _get_fast_tool_schemas)
    # ────────────────────────────────────────────────────────────────────────

    def _get_tool_schemas(self, query: str = "", top_k: int = 100) -> Optional[List[Dict[str, Any]]]:
        """Return tool schemas — NATE warm lookup first, then registry scan.

        Format mirrors the unified loop: ``{"type": "function", "function":
        {"name", "description", "parameters": {"properties", "required"}}}``.
        """
        # The registry is the execution authority.  NATE is an optimization
        # cache and can outlive a registry refresh, so using it as the primary
        # source can advertise stale, unavailable, or skill-only entries that
        # the executor cannot run.
        try:
            if self.tool_registry is None:
                raise RuntimeError("tool registry unavailable")
            schemas: List[Dict[str, Any]] = []
            for name in self.tool_registry.list_tools(include_unavailable=False):
                entry = self.tool_registry.get(name)
                if not entry or not entry.schema:
                    continue
                meta = entry.schema
                params = meta.get("params", {})
                properties = {
                    key: {
                        "type": value.get("type", "string"),
                        "description": str(value.get("description", ""))[:160],
                    }
                    for key, value in params.items()
                }
                required = [key for key, value in params.items() if value.get("required")]
                # MCP and JSON Schema tools commonly declare required fields
                # at the schema level rather than on each property.
                for key in meta.get("required") or []:
                    if key in properties and key not in required:
                        required.append(key)
                schemas.append({"type": "function", "function": {
                    "name": name,
                    "description": str(meta.get("description", ""))[:240],
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                }})
            if len(schemas) > top_k:
                schemas = schemas[:top_k]
            return schemas or None
        except Exception as exc:
            self.logger.warning("Registry schema loading failed: %s", exc)
            # Only use the optional cache when the canonical registry itself
            # is unavailable.  Filter it against no names in that exceptional
            # case because there is no executable authority to consult.
            nate = getattr(self, "_nate", None)
            if nate is not None:
                try:
                    lookup = nate.get_schemas(query, top_k=top_k)
                    if isinstance(lookup, dict):
                        all_schemas = lookup.get("all") or lookup.get("schemas")
                        return list(all_schemas or []) or None
                except Exception as nate_exc:
                    self.logger.warning("Warm NATE schema lookup failed: %s", nate_exc)
            return None

    def _schemas_to_prompt(self, schemas: Optional[List[Dict[str, Any]]]) -> str:
        """Compact, bounded schema text for the planning prompt."""
        if not schemas:
            return ""
        try:
            compact = [
                {
                    "name": s["function"]["name"],
                    "description": s["function"]["description"],
                    "parameters": s["function"]["parameters"],
                }
                for s in schemas
            ]
            return "\nTool schemas (JSON):\n" + json.dumps(compact, ensure_ascii=False)[:16000]
        except Exception:
            return ""

    # ────────────────────────────────────────────────────────────────────────
    # PLANNING
    # ────────────────────────────────────────────────────────────────────────

    async def _plan_with_tool(self, perceived: Any) -> List[Dict[str, Any]]:
        """LLM planning persisted through the real planning tool.

        Generates steps via ``_llm_plan`` (unchanged execution contract) and
        then persists the plan to ``todo.md`` through the registered
        ``planning`` tool (full audit/permission/event pipeline). The tool is
        never allowed to break planning: any failure degrades to returning
        the steps without persistence.
        """
        # The enforcement ladder retries model planning with the same complete
        # discovered schemas when a tool-requiring task gets no concrete plan.
        # It never selects a tool from user keywords.
        # Never let a previous turn's plan leak into a new execution.
        self._active_execution_plan = {}
        steps = await self._llm_plan_with_enforcement(perceived)
        if steps:
            goal = str(getattr(perceived, "original_input", "") or "").strip()
            # Connect the optional Hive safety gate to the live planning
            # boundary.  Keep it behind active mode for compatibility.
            gate = getattr(self, "_gate_plan", None)
            active_mode = getattr(self, "_active_mode_enabled", None)
            if callable(gate) and callable(active_mode) and active_mode():
                steps = await gate(steps, goal)
                if not steps:
                    self.logger.warning(
                        "Plan rejected by active Hive review; skipping persistence"
                    )
                    return []
            persisted = await self._persist_plan_via_tool(goal, steps)
            if not persisted:
                # A plan that exists only in memory is not an execution plan:
                # it cannot be resumed, audited, or reconciled with actions.
                self.logger.warning(
                    "Planning was required but the plan could not be persisted"
                )
                return []
            self._active_execution_plan = self._resolve_active_execution_plan(
                goal, steps
            )
            try:
                await self._emit_plan_event(
                    "pending",
                    goal=goal,
                    steps=[
                        str(step.get("description") or "").strip()
                        for step in steps
                        if isinstance(step, dict)
                        and str(step.get("description") or "").strip()
                    ],
                )
            except Exception as exc:
                self.logger.warning("Plan visibility event failed: %s", exc)
        return steps

    def _resolve_active_execution_plan(
        self, goal: str, steps: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Return the durable plan identity plus the model execution contract."""
        result: Dict[str, Any] = {
            "plan_id": "",
            "goal": str(goal or "")[:4000],
            "steps": [dict(step) for step in steps if isinstance(step, dict)],
            "durable": False,
        }
        try:
            from nexus.control_plane import list_plans

            session_id = str(getattr(self, "session_id", "default") or "default")
            candidates = list_plans(
                str(getattr(self, "root_dir", "") or "."), session_id=session_id
            )
            normalized_goal = str(goal or "").strip().lower()
            for plan in candidates:
                if plan.status != "active":
                    continue
                if str(plan.goal or "").strip().lower() != normalized_goal:
                    continue
                result.update({
                    "plan_id": plan.plan_id,
                    "step_ids": [step.step_id for step in plan.steps],
                    "durable": True,
                })
                break
        except Exception as exc:
            self.logger.debug("Could not resolve durable plan identity: %s", exc)
        return result

    def _plan_spec_from_steps(self, steps: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Build a simple ``plan_spec`` for the planning tool from LLM steps.

        The planning tool requires 3-8 non-empty step descriptions; return
        ``None`` when the plan does not satisfy that contract.
        """
        if not isinstance(steps, list):
            return None
        descriptions = [
            str(step.get("description") or "").strip()
            for step in steps
            if isinstance(step, dict) and str(step.get("description") or "").strip()
        ]
        if not 3 <= len(descriptions) <= 8:
            return None
        return {"plan_type": "simple", "steps": descriptions}

    async def _persist_plan_via_tool(self, goal: str, steps: List[Dict[str, Any]]) -> bool:
        """Persist the LLM plan to todo.md through the ``planning`` tool.

        Routes a ``planning`` create call through ``_run_tool`` so the plan
        write is audited, lifecycle-marked and streamed as a normal tool
        event. Returns ``True`` on persistence, ``False`` on any failure.
        """
        self._last_planning_error = ""
        spec = self._plan_spec_from_steps(steps)
        if not spec:
            count = len(steps) if isinstance(steps, list) else 0
            self._last_planning_error = (
                f"planner returned {count} steps; 3-8 non-empty steps are required"
            )
            self.logger.debug(
                "Skipping planning tool: plan has %d step(s) (3-8 required)", count
            )
            return False
        run_tool = getattr(self, "_run_tool", None)
        if not callable(run_tool):
            self._last_planning_error = "planning tool executor is unavailable"
            return False
        call = SimpleNamespace(
            name="planning",
            call_id="",
            params={
                "action": "create",
                "goal": goal,
                "plan_spec": spec,
                "session_id": str(getattr(self, "session_id", "default") or "default"),
            },
        )
        try:
            result = await run_tool(call)
            # The normal V5 executor raises on failure and returns text on
            # success.  Test adapters and future executors may return a typed
            # ToolResult, so honor an explicit unsuccessful result as well.
            if hasattr(result, "success") and not bool(result.success):
                self._last_planning_error = str(
                    getattr(result, "error", "planning tool returned failure")
                    or "planning tool returned failure"
                )[:4000]
                return False
            self.logger.info("Plan persisted to todo.md via planning tool")
            return True
        except Exception as exc:
            self._last_planning_error = str(exc)[:4000] or "planning tool execution failed"
            self.logger.warning(
                "Planning tool failed; plan will not be persisted: %s", exc
            )
            return False

    async def _request_plan_approval(self, goal: str, steps: List[Dict[str, Any]]) -> bool:
        """Gate plan execution on human approval (APPROVE mode only).

        Opens a plan-level request on the shared ``ApprovalBroker``, emits
        the human-facing ``tool.approval_request`` event the GUI already
        renders, and awaits the decision. Every other permission mode
        passes through immediately.

        Approval mode is fail-closed: a missing broker or broken approval
        plumbing must not silently authorize side effects. Other permission
        modes pass through immediately.

        Args:
            goal: The user's original request text.
            steps: Plan step dicts (``{"description", "tool", "params"}``).

        Returns:
            True when the plan may proceed (approved, or no gate needed).
        """
        try:
            if self._permission_mode() != "APPROVE":
                return True
            broker = self._approval_broker()
            if broker is None:
                self.logger.warning(
                    "Plan approval requested but no approval broker is "
                    "available; blocking execution"
                )
                return False
            descriptions = [
                str(step.get("description") or "").strip()
                for step in steps or []
                if isinstance(step, dict)
                and str(step.get("description") or "").strip()
            ]
            request = broker.open(
                session_id=self.session_id,
                tool_name="plan",
                action=f"Approve plan: {str(goal or '')[:120]}",
                reason="; ".join(descriptions[:8]),
                turn_id=self._current_turn_id,
                timeout_s=300.0,
            )
            try:
                await self._emit_work_event(request.to_event())
            except Exception as exc:
                self.logger.warning("Plan approval request event failed: %s", exc)
            decision = await broker.wait(request.request_id)
            return decision in ("allow", "allow_always")
        except Exception as exc:
            self.logger.warning("Plan approval gate failed closed: %s", exc)
            return False

    def _planning_system_prompt(self) -> str:
        available = ""
        try:
            if self.tool_registry is not None:
                names = list(self.tool_registry.list_tools().keys())
                if names:
                    available = " Available tools: " + ", ".join(sorted(names)[:60]) + "."
        except Exception:
            pass
        schema_text = self._schemas_to_prompt(self._get_tool_schemas(top_k=100))
        return (
            "You are the planning module of an autonomous agent. Given a user "
            "request, produce a concise JSON execution plan with the exact "
            "shape: "
            '{"steps": [{"description": "...", "tool": "<name>", "params": {...}}]}.'
            "Use an empty string for \"tool\" when a step needs no tool."
            ' Choose tool names and parameter keys ONLY from the schemas below;'
            " never invent tools."
            + available
            + schema_text
            + " Respond with ONLY the JSON object."
        )

    async def _llm_plan(self, perceived: Any) -> List[Dict[str, Any]]:
        """Real LLM planning: returns a list of step dicts (empty on failure).

        Falls back to extracting free-text tool calls from the model reply
        when the JSON plan cannot be parsed - mirroring the unified loop's
        ``_extract_tool_calls`` retry ladder.
        """
        abort = getattr(self, "_check_abort", None)
        if callable(abort):
            try:
                await abort()
            except Exception:
                return []
        intent = getattr(getattr(perceived, "intent", None), "value", "chat")
        context = str(getattr(perceived, "context_summary", "") or "")
        context_line = f"\nRelevant context: {context[:2000]}" if context else ""
        messages = [
            {"role": "system", "content": self._planning_system_prompt()},
            {
                "role": "user",
                "content": (
                    f"Task: {perceived.original_input}\n"
                    f"Detected intent: {intent}\n"
                    f"{context_line}\n"
                    "Return ONLY the JSON plan."
                ),
            },
        ]
        # Give OpenAI-compatible providers the real schemas as well as the
        # compact prompt. This lets providers such as OpenRouter/Nemotron
        # return native, validated tool calls instead of guessing JSON fields.
        raw = await self._safe_model_call(
            messages,
            timeout=90.0,
            tools=self._get_tool_schemas(top_k=100),
            tool_choice="auto",
        )
        if callable(abort):
            try:
                await abort()
            except Exception:
                return []
        steps = self._parse_plan_json(raw)
        if steps:
            return steps
        text_steps = self._plan_from_text(raw, str(perceived.original_input))
        if not text_steps:
            # A tool-requiring task that yields no plan must be visible, not
            # silently empty — the turn path uses it for retry decisions.
            try:
                emitter = getattr(self, "_emit_plan_event", None)
                if callable(emitter):
                    emit = emitter(
                        "failed",
                        goal=str(getattr(perceived, "original_input", "") or "").strip(),
                        steps=[],
                    )
                    if inspect.isawaitable(emit):
                        await emit
            except Exception:
                pass
        return text_steps

    def _plan_from_text(self, raw: str, task: str) -> List[Dict[str, Any]]:
        """V1-style fallback: extract tool calls from free-text model output."""
        extractor = getattr(self, "_extract_tool_calls_from_text", None)
        if not callable(extractor):
            return []
        calls = extractor(raw or "")
        steps: List[Dict[str, Any]] = []
        for call in calls:
            steps.append({
                "description": f"Execute {call.name}",
                "tool": call.name,
                "params": call.params or {},
            })
        if steps:
            self.logger.info("Extracted %d tool call(s) from model text", len(steps))
        return steps

    def _parse_plan_json(self, raw: str) -> List[Dict[str, Any]]:
        """Robustly parse the LLM's JSON plan into a list of step dicts.

        Steps that name an unknown tool are dropped with a warning (when the
        registry is available) so execution never runs a misspelled tool.
        """
        if not raw:
            return []
        text = raw.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        data = None
        try:
            data = json.loads(text)
        except Exception:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(0))
                except Exception:
                    data = None
        if isinstance(data, dict):
            steps = data.get("steps")
        elif isinstance(data, list):
            steps = data
        else:
            steps = None
        if not isinstance(steps, list):
            return []

        known: Optional[set] = None
        try:
            if self.tool_registry is not None:
                known = set(self.tool_registry.list_tools().keys())
                known |= set(getattr(self, "COMMAND_ALIASES", ()))
        except Exception:
            known = None

        cleaned: List[Dict[str, Any]] = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            description = str(step.get("description") or step.get("task") or "").strip()
            if not description:
                continue
            tool = str(step.get("tool") or step.get("tool_name") or "").strip()
            if known is not None and tool and tool not in known:
                self.logger.warning(
                    "Plan step dropped: unknown tool '%s' (step: %s)", tool, description[:80]
                )
                continue
            params = step.get("params")
            cleaned.append({
                "description": description,
                "tool": tool,
                "params": params if isinstance(params, dict) else {},
            })
        return cleaned
