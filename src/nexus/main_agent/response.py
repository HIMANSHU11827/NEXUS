"""V5 Response Builder - Final answer generation for the V5 loop.

Extracted from ``core.py``. Streams the real model response built
from perception, plan, tool observations and reflection; composes an honest
evidence-based fallback when the model is unavailable.

Includes response-hygiene machinery ported from V1 (``orchestrators/loop.py``):
provider tool envelopes, fenced/XML/JSON tool protocol and raw tool-result
dumps are stripped from the final chat answer, and public ``<progress>``
notes are extracted and surfaced as runtime events instead of leaking into
the response.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple


class V5ResponseBuilder:
    @staticmethod
    def _provider_failure_kind(raw_error: str) -> str:
        low = str(raw_error or "").lower()
        if any(token in low for token in ("insufficient_quota", "quota exceeded", "credit", "balance", "billing", "payment required", "status 402", "http 402")):
            return "quota_or_billing"
        if any(token in low for token in ("missing", "no api key", "no credential", "not set")):
            return "missing_credentials"
        if any(token in low for token in ("401", "403", "invalid api key", "invalid key", "authentication", "unauthorized", "forbidden", "rejected")):
            return "authentication"
        if any(token in low for token in ("timeout", "connection", "network", "temporarily", "503", "502", "500")):
            return "connectivity"
        return "provider_failure"

    def _provider_failure_message(self, raw_error: str) -> str:
        """Turn provider failures into actionable, secret-free guidance."""
        error = str(raw_error or "")
        low = error.lower()
        provider = ""
        brain = getattr(self, "brain", None)
        active = getattr(brain, "provider", None)
        routed_name = getattr(brain, "provider_override", "")
        if not routed_name and callable(getattr(brain, "_get_provider_name", None)):
            try:
                routed_name = brain._get_provider_name()
            except Exception:
                routed_name = ""
        provider = str(
            getattr(self, "_provider_hint", "")
            or
            getattr(active, "provider_name", "")
            or routed_name
            or getattr(brain, "_provider_id", "")
            or os.environ.get("NEXUS_PROVIDER", "")
            or "configured provider"
        ).strip()
        if provider.lower() in {"configured provider", "none", "unknown"}:
            provider = ""
        env_provider = re.sub(r"[^A-Za-z0-9]", "_", provider).upper()
        key_hint = f"{env_provider}_API_KEY" if env_provider and env_provider != "CONFIGURED_PROVIDER" else "the provider's configured API key"
        if self._provider_failure_kind(error) == "quota_or_billing":
            selected = f" '{provider}'" if provider else ""
            return f"NEXUS reached the selected provider{selected}, but its account balance, credit, or quota is exhausted. Add credit or choose another enabled provider/profile, then Retry. This is not an API-key configuration error."
        if any(token in low for token in ("unsupported provider", "unknown provider", "not configured")):
            selected = f" '{provider}'" if provider else ""
            return f"NEXUS could not use the selected provider{selected}: it is not configured or supported. Open Settings → Providers, choose a configured provider, then Retry."
        if any(token in low for token in ("missing", "no api key", "no credential", "not set")):
            selected = f" '{provider}'" if provider else ""
            return f"NEXUS could not get an AI response because the selected provider{selected} is missing {key_hint}. Open Settings → Providers, set it in config/provider.yml or the environment, then Retry."
        if any(token in low for token in ("401", "403", "invalid api key", "invalid key", "authentication", "unauthorized", "forbidden", "rejected")):
            selected = f" (selected provider: '{provider}')" if provider else ""
            return f"NEXUS could not get an AI response because the configured provider rejected its API key{selected}. Check {key_hint} in Settings → Providers, then Retry. A configured fallback is a separate provider and is only implicated if its own failure is reported."
        if any(token in low for token in ("timeout", "connection", "network", "temporarily", "503", "502", "500")):
            selected = f" '{provider}'" if provider else ""
            return f"NEXUS could not get an AI response because the selected provider{selected} is temporarily unavailable. Check connectivity or provider status, then Retry."
        selected = f" '{provider}'" if provider else ""
        return f"NEXUS could not get an AI response because the selected provider{selected} failed. Open Settings → Providers and Retry."

    """Mixin providing final-answer streaming and fallback composition."""

    async def _generate_output(
        self,
        perceived,
        result: Dict[str, Any],
        *,
        provider: Optional[str] = None,
        profile: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream the final answer, then yield the output dict.

        Yields {"chunk": text, "type": "text-delta"} events while the model
        streams, followed by a single {"output": {...}, "type": "finish"} event.
        When the model is unavailable the response falls back to text composed
        from the real plan and tool observations. Streamed text is run through
        response hygiene: tool protocol envelopes are stripped, ``<progress>``
        notes are surfaced as runtime events, and any answer that still looks
        like raw tool transport is replaced by the fallback.
        """
        self._provider_hint = provider or ""
        messages, fallback = self._compose_output_messages(perceived, result)
        response = ""
        try:
            async for chunk in self._stream_model(
                messages, provider=provider, profile=profile, model=model, max_tokens=max_tokens
            ):
                if self._abort_requested():
                    break
                if not chunk:
                    continue
                response += chunk
                yield {"chunk": chunk, "type": "text-delta"}
        except Exception as e:
            self.logger.warning(f"Output streaming failed: {e}")
            # The provider error is discovered during streaming, after the
            # initial fallback was composed. Rebuild it so the user sees the
            # real configuration/connection problem instead of a generic
            # processed-request message.
            if getattr(self, "_last_model_error", ""):
                # A provider may have emitted retry chatter before raising.
                # Discard every partial chunk and use the sanitized provider
                # failure fallback instead.
                response = ""
                _, fallback = self._compose_output_messages(perceived, result)

        stripped, notes = self._extract_progress_notes(response)
        stripped = self._strip_internal_tool_protocol(stripped)

        # A provider can produce a plausible-looking but contradictory final
        # sentence after a real tool attempt (most often: "no tools were
        # executed" after a failed search/command).  Never show that claim
        # when the execution envelope contains tool evidence; the deterministic
        # fallback names the actual failure and preserves the user's evidence.
        tool_text = self._describe_tool_results(result)
        if stripped.strip() and tool_text and self._claims_no_tools_executed(stripped):
            stripped = fallback

        run_id = self._current_turn_id or self.session_id
        for idx, note in enumerate(notes):
            await self._emit_runtime_event(
                "assistant.progress",
                note,
                "running",
                event_id=f"progress_{run_id}_{idx}",
                parent_id=f"run_{run_id}",
                payload={"note": note},
            )

        if not stripped.strip():
            response = fallback
        elif self._contains_tool_protocol(stripped):
            response = fallback
        elif self._is_raw_tool_result_dump(stripped):
            response = fallback
        else:
            response = stripped

        yield {"output": {"response": response, "used_fallback": response == fallback}, "type": "finish"}

    @staticmethod
    def _extract_progress_notes(response: str) -> Tuple[str, List[str]]:
        """Split public ``<progress>`` narration out of a model response.

        Returns ``(response_without_tags, notes)``. Notes are short user-facing
        status lines describing the next action — they are deliberately public
        (unlike reasoning/thinking blocks, which are never surfaced). Unclosed or
        empty tags are ignored and the text is left untouched.
        """
        text = str(response or "")
        if "<progress>" not in text.lower():
            return text, []
        notes: List[str] = []

        def _take(match: "re.Match[str]") -> str:
            note = match.group(1).strip()
            if note:
                notes.append(note)
            return ""

        pattern = re.compile(r"<progress>(.*?)</progress>", re.DOTALL | re.IGNORECASE)
        cleaned = pattern.sub(_take, text)
        return cleaned, notes

    @staticmethod
    def _strip_internal_tool_protocol(response: str) -> str:
        """Remove provider tool envelopes and raw JSON tool calls that must never become chat text."""
        cleaned = str(response or "")

        def _is_tool_payload(text: str) -> bool:
            """Check if text is JSON containing tool call structure."""
            text = text.strip()
            if not text:
                return True
            if not ((text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]"))):
                return False
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                return False
            if isinstance(obj, list):
                return len(obj) == 0 or all(isinstance(item, dict) for item in obj)
            if not isinstance(obj, dict):
                return False
            if "action" in obj and "params" in obj:
                return True
            if "name" in obj and "params" in obj:
                return True
            if "tool" in obj and "params" in obj:
                return True
            return False

        def _strip_fences(text: str) -> str:
            """Remove fenced JSON tool calls and known tool protocol blocks."""
            result = []
            i = 0
            while i < len(text):
                fence = re.search(r"```(\w*)\s*\n?", text[i:])
                if not fence:
                    result.append(text[i:])
                    break
                result.append(text[i:i + fence.start()])
                lang = fence.group(1).lower()
                content_start = i + fence.end()
                close = re.search(r"```", text[content_start:])
                if not close:
                    result.append(text[i + fence.start():])
                    break
                content = text[content_start:content_start + close.start()]
                fence_end = content_start + close.end()
                if lang in ("tool_use", "tool"):
                    i = fence_end
                elif lang in ("json", "") and _is_tool_payload(content):
                    i = fence_end
                else:
                    result.append(text[i + fence.start():fence_end])
                    i = fence_end
            return "".join(result)

        stripped = _strip_fences(cleaned)
        # XML tool tags — catch all variants
        stripped = re.sub(
            r"<(tool_use|tool_calls|tool_call|function_calls|function_call|invoke|invocation)>[\s\S]*?</\1>", "", stripped,
            flags=re.IGNORECASE | re.DOTALL,
        )
        # DeepSeek emits the same envelope with full-width DSML delimiters.
        # It is still transport markup and must never reach the final answer.
        stripped = re.sub(
            r"<[^<>]*DSML[^<>]*tool_calls[^>]*>[\s\S]*?</[^<>]*DSML[^<>]*tool_calls\s*>", "", stripped,
            flags=re.IGNORECASE | re.DOTALL,
        )
        # Some providers emit the canonical tool name directly as an XML
        # element (for example ``<web_search>...</web_search>``).  These are
        # transport envelopes, not user-facing prose, so remove the complete
        # block before a final response is streamed.
        stripped = re.sub(
            r"<(?:web_search|code_search|reading|creating|modifying|deleting|bash|http_client|git_ops|test_runner|planning|hive|browser|search|knowledge|reasoning|task|system|deep_research|shortcuts|terminal|memory)[^>]*>[\s\S]*?</(?:web_search|code_search|reading|creating|modifying|deleting|bash|http_client|git_ops|test_runner|planning|hive|browser|search|knowledge|reasoning|task|system|deep_research|shortcuts|terminal|memory)>",
            "",
            stripped,
            flags=re.IGNORECASE | re.DOTALL,
        )
        stripped = re.sub(
            r"<invoke\s+name=\"\w+\">[\s\S]*?</invoke>", "", stripped,
            flags=re.IGNORECASE | re.DOTALL,
        )
        # Compact self-closing XML tool tags: <tool name="x" param="y"/>
        stripped = re.sub(
            r"<[a-z_]+(?:\s+[a-z_]+=\"[^\"]*\")*\s*/>", "", stripped,
            flags=re.DOTALL,
        )
        # Inline function-call syntax: word({...}) or tool.word({...})
        stripped = re.sub(
            r"\b(?:[a-z_]+\.)?[a-z_]+\(\{.*?\}\)", "", stripped,
            flags=re.DOTALL,
        )
        # Provider function-call format: <function=name>{json} or <function=name>...</function>
        stripped = re.sub(
            r"<function=\w+>(?:[\s\S]*?</function>)?", "", stripped,
            flags=re.IGNORECASE | re.DOTALL,
        )
        # DeepSeek/OpenAI-compatible function envelopes. Strip the whole block
        # so protocol text can never become a chat response.
        stripped = re.sub(
            r"<function:\s*[\w.-]+>\s*[\s\S]*?(?:</function>|$)", "", stripped,
            flags=re.IGNORECASE | re.DOTALL,
        )
        stripped = re.sub(
            r"<function\s*>\s*[\s\S]*?</function>", "", stripped,
            flags=re.IGNORECASE | re.DOTALL,
        )
        # Remove standalone JSON tool calls like {"action": "tool", "params": {...}}
        def _strip_standalone_json(text: str) -> str:
            result = []
            depth = 0
            start = -1
            for i, ch in enumerate(text):
                if ch == "{":
                    if depth == 0:
                        start = i
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0 and start != -1:
                        candidate = text[start:i+1]
                        try:
                            obj = json.loads(candidate)
                            if isinstance(obj, dict) and "action" in obj and "params" in obj:
                                result.append("")
                            elif isinstance(obj, dict) and "name" in obj and "params" in obj:
                                result.append("")
                            elif isinstance(obj, dict) and "tool" in obj and "params" in obj:
                                result.append("")
                            else:
                                result.append(candidate)
                        except json.JSONDecodeError:
                            result.append(candidate)
                        start = -1
                elif depth == 0:
                    result.append(ch)
            return "".join(result)
        stripped = _strip_standalone_json(stripped)
        # Collapse runs of 3+ blank lines to at most one and trim edges.
        stripped = re.sub(r"\n{3,}", "\n\n", stripped).strip()
        return stripped

    @staticmethod
    def _contains_tool_protocol(response: str) -> bool:
        """Identify provider tool envelopes, but never ordinary explanatory prose."""
        return bool(re.search(
            r"<function(?:\s*(?:=|:)\s*[\w.-]+)?\s*>|<[^<>]*DSML[^<>]*tool_calls\b|<(?:tool_use|tool_calls|tool_call|invoke|web_search|code_search|reading|creating|modifying|deleting|bash|http_client|git_ops|test_runner|planning|hive|browser|search|knowledge|reasoning|task|system|deep_research|shortcuts|terminal|memory)\b",
            str(response or ""),
            flags=re.IGNORECASE,
        ))

    def _compose_output_messages(self, perceived, result: Dict[str, Any]):
        """Build the final-answer prompt and the no-model fallback text."""
        intent = getattr(getattr(perceived, "intent", None), "value", "chat")
        context = str(getattr(perceived, "context_summary", "") or "")

        plan_text = self._describe_plan(result)
        tool_text = self._describe_tool_results(result)
        reflection_text = self._describe_reflection(result)

        system_prompt = (
            "You are NEXUS, an autonomous AI agent operating inside your own "
            "workspace. You have already executed a plan with real tool "
            "observations. Write a natural, direct final response to the user "
            "that: (1) summarizes what was done, using the tool observations "
            "below as evidence; (2) reports concrete results, errors, and next "
            "steps if any; (3) never invents facts not present in the "
            "observations. Keep it concise and conversational."
        )
        user_prompt = (
            f"User request: {perceived.original_input}\n\n"
            f"Detected intent: {intent}\n"
            f"Context: {context[:4000]}\n\n"
            f"Execution plan:\n{plan_text or '(no steps)'}\n\n"
            f"Tool results:\n{tool_text or '(no tools executed)'}\n\n"
            f"Reflection:\n{reflection_text or '(none)'}\n\n"
            "IMPORTANT: The tool results above are REAL. They were actually executed. "
            "Report exactly what happened based on the tool results. "
            "If tools succeeded, say what was created/done. "
            "If tools failed, say what failed. Never claim tools didn't run "
            "when tool results are present above.\n\n"
            "Respond with the final answer to the user now."
        )

        fallback = self._compose_fallback_response(perceived, result, plan_text, tool_text)
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ], fallback

    def _describe_plan(self, result: Dict[str, Any]) -> str:
        plan = result.get("plan")
        if plan is None:
            return ""
        if isinstance(plan, dict):
            steps = plan.get("steps") or []
        else:
            steps = getattr(plan, "steps", None) or []
        lines = []
        for step in steps:
            if isinstance(step, dict):
                description = step.get("description") or step.get("task") or ""
                tool = step.get("tool") or ""
            else:
                description = getattr(step, "description", "") or ""
                tool = ""
            line = f"- {description}"
            if tool:
                line += f" (tool: {tool})"
            lines.append(line)
        return "\n".join(lines)

    def _describe_tool_results(self, result: Dict[str, Any]) -> str:
        """Extract tool results from any result format."""
        # Try multiple possible action locations
        plan = result.get("plan") if isinstance(result, dict) else None
        if isinstance(plan, dict):
            plan_actions = plan.get("actions")
        else:
            plan_actions = getattr(plan, "actions", None)
        actions = result.get("actions") or plan_actions or []
        if not actions and hasattr(result, "actions"):
            actions = result.actions or []
        if not isinstance(actions, list):
            try:
                actions = list(actions)
            except Exception:
                actions = []

        # Some execution adapters wrap the action list in ``result`` or use
        # ``results``/``tool_results``.  Preserve those records instead of
        # allowing the final prompt to say ``(no tools executed)`` after a
        # real tool ran and failed.
        if not actions:
            for key in ("tool_results", "results", "result"):
                candidate = result.get(key) if isinstance(result, dict) else None
                if isinstance(candidate, list):
                    actions = candidate
                    break
                if isinstance(candidate, dict) and any(
                    field in candidate for field in ("output", "error", "success", "tool", "name")
                ):
                    actions = [candidate]
                    break

        lines = []
        for action in actions:
            output = ""; error = ""; description = ""; success = True
            if isinstance(action, dict):
                # Reasoning-only plan entries are not tool evidence.  They
                # must not make the final answer claim that tools completed.
                if not (action.get("tool") or action.get("name")):
                    continue
                output = str(action.get("output") or "")
                error = str(action.get("error") or action.get("exception") or "")
                description = str(
                    action.get("description")
                    or action.get("tool")
                    or action.get("name")
                    or action.get("step_id")
                    or ""
                )
                status = str(action.get("status") or "").lower()
                success = bool(action.get("success", status not in {"failed", "error", "cancelled"}))
                if status in {"failed", "error", "cancelled"} and not error:
                    error = status
            elif hasattr(action, "output"):
                output = str(getattr(action, "output", "") or "")
                error = str(getattr(action, "error", "") or "")
                description = str(getattr(action, "step_id", "") or getattr(action, "description", "") or "")
                success = bool(getattr(action, "success", True))
            elif action is not None:
                output = str(action)[:500]

            if error:
                lines.append(f"- {description}: FAILED: {error}" if description else f"- FAILED: {error}")
            elif output:
                label = f"- {description}: " if description else "- "
                lines.append(f"{label}{output[:2000]}")
            elif description:
                lines.append(f"- {description}: {'completed' if success else 'failed'}")

        return "\n".join(lines) if lines else ""

    @staticmethod
    def _claims_no_tools_executed(response: str) -> bool:
        """Return whether final prose falsely denies an observed tool run."""
        return bool(re.search(
            r"\b(?:no|none|without)\s+(?:\w+\s+){0,3}tools?\s+(?:were\s+)?executed\b"
            r"|\bno\s+tools?\s+(?:ran|run|were\s+used)\b"
            r"|\btools?\s+(?:were\s+not|weren't)\s+(?:executed|run|used)\b",
            str(response or ""),
            flags=re.IGNORECASE,
        ))

    def _describe_reflection(self, result: Dict[str, Any]) -> str:
        reflection = result.get("reflection")
        if reflection is None:
            return ""
        if isinstance(reflection, dict):
            success = bool(reflection.get("success"))
            causes = reflection.get("root_causes") or []
            confidence = reflection.get("confidence", 0.0)
        else:
            success = bool(getattr(reflection, "success", False))
            causes = getattr(reflection, "root_causes", None) or []
            confidence = getattr(reflection, "confidence", 0.0)
        text = f"success={success}, confidence={confidence:.2f}"
        if causes:
            text += "; causes: " + "; ".join(str(c) for c in causes)
        return text

    def _compose_fallback_response(
        self,
        perceived,
        result: Dict[str, Any],
        plan_text: str = "",
        tool_text: str = "",
    ) -> str:
        """No-model fallback: honest summary of the real execution evidence."""
        lines = []
        if plan_text:
            lines.append("I planned the following steps:")
            lines.append(plan_text)
        if tool_text:
            lines.append("\nExecution results:")
            lines.append(tool_text)

        # A direct conversational turn can still carry ``success=True`` from
        # the execution envelope.  That does not mean a plan ran, so do not
        # claim that "all steps" completed unless there is actual evidence.
        actions = result.get("actions") or []
        has_tool_actions = any(
            isinstance(action, dict) and (action.get("tool") or action.get("name"))
            for action in actions
        )
        has_execution_evidence = bool(tool_text or has_tool_actions)
        if plan_text and not has_execution_evidence:
            lines.append("\nA plan was created, but no tool was executed.")
        success = result.get("success")
        if success is not None and has_execution_evidence:
            if success:
                lines.append("\nAll steps completed successfully.")
            else:
                lines.append("\nSome steps did not complete; details above.")
        if not lines:
            model_error = str(getattr(self, "_last_model_error", "") or "")
            if model_error:
                lines.append(self._provider_failure_message(model_error))
            else:
                lines.append(f"Processed your request: {perceived.original_input}")
        return "\n".join(lines)
