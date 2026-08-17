"""
NEXUS PROMPT ENGINE — Token-efficient dynamic prompts.
Generates tool lists from registry. No hardcoded fluff.
"""

import json
import os
import platform
from datetime import datetime
from typing import Any, Dict, List


class NexusPromptEngine:
    """
    Token-efficient prompt builder.
    Dynamic tool listing from registry. Minimal identity overhead.
    """

    IDENTITY: str = (
        "# NEXUS_ENGINEERING_CORE v21.1 | Local-First Autonomous Engineering Agent\n"
        f"# DATE: {datetime.now().strftime('%Y-%m-%d')}\n"
        "# MISSION: Fast autonomous engineering with codebase awareness, memory, tools, and verification.\n"
        "# EXECUTION: Direct action is preferred. Avoid approval spam. Use deterministic risk filters, path protection, timeouts, and rollback design.\n"
        "# HONESTY: Never fake capabilities. If a system is shallow, call it shallow and improve the real implementation.\n"
        "# RULE: Verify from actual code and behavior before making claims.\n"
        "# WINDOWS_TERMINAL: cmd.exe is the default; use &/&& instead of unquoted ';' and avoid Unix-only head/tail. Choose shell='powershell' explicitly when needed."
    )

    @staticmethod
    def get_role_segment(role: str = "ARCHITECT") -> str:
        """Get role-specific segment."""
        roles: Dict[str, str] = {
            "ARCHITECT": "# ROLE: ARCHITECT (Structure Focus)",
            "DEBUGGER": "# ROLE: DEBUGGER (Root Cause Focus)",
            "SECURITY": "# ROLE: SECURITY (Safety Focus)",
            "HIVE": "# ROLE: HIVE (Parallel Focus)",
        }
        return roles.get(role.upper(), roles["ARCHITECT"])

    @staticmethod
    def get_adaptive_collaboration_segment(intent: str = "chat", complexity: str = "simple", needs_tools: bool = False) -> str:
        """
        Describe NEXUS as one continuous collaborator, not a set of user-facing modes.

        The runtime may change posture internally, but the user should experience
        one capable coworker that naturally shifts between conversation, coding,
        operations, review, and strategy.
        """
        posture = "companion"
        if needs_tools:
            posture = "worker"
        if intent in {"code", "debug", "test", "files", "reading", "creating", "modifying", "deleting", "git"}:
            posture = "engineer"
        elif intent in {"research"}:
            posture = "researcher"
        elif intent in {"hive"} or complexity == "complex":
            posture = "operator"
        elif intent in {"strategy", "cognition"}:
            posture = "strategist"

        return (
            "# ADAPTIVE_COLLABORATION:\n"
            "# - Be one continuous NEXUS coworker, not separate chat/worker/CEO modes.\n"
            "# - Shift posture naturally: friend for human conversation, engineer for code, worker for execution, reviewer for risk, strategist for priorities.\n"
            "# - Decide tool use from the task and evidence. Casual talk should stay conversational; real work should move to files, shell, tests, memory, or diagnostics.\n"
            "# - For broad or many-part missions, spawn scoped Hive workers and integrate their results instead of doing every task alone.\n"
            "# - For broad ambition, convert it into concrete repo improvements, measurable checks, and next actions.\n"
            f"# - Current internal posture hint: {posture}; intent={intent}; complexity={complexity}; needs_tools={needs_tools}."
        )

    @staticmethod
    def get_identity_segment() -> str:
        """Get identity segment."""
        return NexusPromptEngine.IDENTITY

    @staticmethod
    def get_environment_segment(root_dir: str, context_map: str) -> str:
        """Get environment grounding segment (Includes Hardware Footprint)."""
        from nexus.runtime.kernel import get_nexus_kernel
        kernel = get_nexus_kernel()
        hw_footprint = kernel.hal.get_hardware_footprint()
        
        trimmed_map = (
            context_map[:3000] + "..." if len(context_map) > 3000 else context_map
        )
        return (
            f"# ENV: {platform.system()} | Root: {root_dir}\n"
            f"# HARDWARE: {hw_footprint}\n"
            f"# Grounding: {trimmed_map}"
        )

    @staticmethod
    def get_tool_segment(intent_hints: List[str] = None) -> str:
        """Expose the real available tool list to the model."""
        try:
            from extensions.tools.built_in.nexus_tools.registry import ToolRegistry
            registry = ToolRegistry()
            tools: List[str] = []
            seen: set = set()
            
            for name in registry.list_tools(include_unavailable=False):
                tool = registry.get(name)
                if not tool or tool.name in seen:
                    continue
                seen.add(tool.name)
                desc = str(
                    getattr(tool, "description", "")
                    or (getattr(tool, "schema", {}) or {}).get("description", "")
                ).strip()[:80]
                tools.append(f"{tool.name}: {desc}")

            tool_list = "\n".join(f"  {i + 1}. {t}" for i, t in enumerate(tools))
            question_rule = (
                "\n# INTERACTION_RULE: When you need information, clarification, or a choice from the user, "
                "call ask_question with a concise prompt and options. Do not ask through ordinary prose, "
                "do not emit [QUESTION:...] yourself, and wait for the user's answer."
                if "ask_question" in seen else ""
            )
            return (
                "# 🧰_TOOLS (JSON ONLY):\n"
                f"{question_rule}\n"
                f"{tool_list}\n"
                '# FMT: {"action": "tool_name", "params": {...}}\n'
                '# Use the exact tool names shown above. Prefer tools over guessing.'
            )
        except Exception:
            return (
                "# 🧰_TOOLS: bash, code_search, reading, creating, modifying, deleting, "
                "git_ops, hive, memory, system, task, terminal, test_runner, web_search"
            )

    @staticmethod
    def get_rules_segment(root_dir: str) -> str:
        """Load ALL project rules from nexus.json (cached)."""
        rules_text: str = ""
        manifest_path = os.path.join(root_dir, "nexus.json")
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r") as f:
                    data = json.load(f)
                    rules = data.get("rules", [])
                    if rules:
                        rules_text = "# RULES: " + " | ".join(rules) # Show all rules
            except (OSError, json.JSONDecodeError, ValueError):
                pass
        return rules_text

    @staticmethod
    def get_special_focus_segment(root_dir: str) -> str:
        """Load durable audit/repair focus instructions for NEXUS itself."""
        path = os.path.join(root_dir, "docs", "SPECIAL_FOCUS.md")
        if not os.path.exists(path):
            return ""
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if not content:
                return ""
            trimmed = content[:5000] + "\n...[truncated]" if len(content) > 5000 else content
            return f"# SPECIAL_FOCUS_DIRECTIVE:\n{trimmed}"
        except OSError:
            return ""

    @staticmethod
    def _get_environment_line(root_dir: str, context_map: str = "") -> str:
        """One compact environment-grounding line (safe: never raises).

        Unlike ``get_environment_segment`` this stays on a single line and
        any kernel/hardware failure degrades to a static line so prompt
        building can never crash the live loop.
        """
        line = f"# ENV: {platform.system()} | Root: {root_dir}"
        try:
            from nexus.runtime.kernel import get_nexus_kernel
            kernel = get_nexus_kernel(root_dir=root_dir)
            hal = getattr(kernel, "hal", None)
            if hal is not None:
                footprint = hal.get_hardware_footprint()
                if footprint:
                    line += f" | HW: {str(footprint)[:120]}"
        except Exception:
            pass
        if context_map:
            trimmed = context_map[:300] + "..." if len(context_map) > 300 else context_map
            line += f" | Grounding: {trimmed}"
        return line

    @classmethod
    def build_live_system_prompt(
        cls,
        root_dir: str,
        *,
        role: str = "ARCHITECT",
        intent: str = "chat",
        complexity: str = "simple",
        needs_tools: bool = False,
        context_map: str = "",
        max_chars: int = 4000,
    ) -> str:
        """Assemble a COMPACT, token-budgeted live system prompt.

        Uses only the light, safe segments (identity, adaptive-collaboration,
        role, project rules, special-focus, one-line env). Never calls the
        heavy ``build_super_prompt`` (KnowledgeVault + kernel.horizons). Each
        segment is wrapped so a raised segment is skipped — prompt building
        must never crash the live loop — and the total is trimmed to respect
        *max_chars*.
        """
        builders = (
            cls.get_identity_segment,
            lambda: cls.get_adaptive_collaboration_segment(intent, complexity, needs_tools),
            lambda: cls.get_role_segment(role),
            cls.get_tool_segment,
            lambda: cls.get_rules_segment(root_dir),
            lambda: cls.get_special_focus_segment(root_dir),
            lambda: cls._get_environment_line(root_dir, context_map),
        )
        segments: List[str] = []
        for build in builders:
            try:
                segment = str(build() or "").strip()
            except Exception:
                segment = ""
            if segment:
                segments.append(segment)
        compact = "\n".join(segments)
        if len(compact) > max_chars:
            compact = compact[: max(0, max_chars - 3)] + "..."
        return compact

    @classmethod
    def build_super_prompt(
        cls,
        root_dir: str,
        context_map: str,
        role: str = "ARCHITECT",
        intent_hints: List[str] = None,
        intent: str = "chat",
        complexity: str = "simple",
        needs_tools: bool = False,
    ) -> str:
        # 🧪 3.8: EXPERIENTIAL RECALL (Dynamic Memory Injection)
        from knowledge.vault import KnowledgeVault
        vault = KnowledgeVault() # Fixed: no args → uses default knowledge/vault.json.enc path
        experience = vault.retrieve_as_text("mission lesson discovery architecture", top_k=2)
        
        # ⚡ 4.0: STRATEGIC HORIZONS (Long-term Persistence)
        from nexus.runtime.kernel import get_nexus_kernel
        kernel = get_nexus_kernel()
        kernel.horizons.get_active_horizons()
        
        segments: List[str] = [
            cls.get_identity_segment(),
            "# SYSTEM: Collaborator. BE SHORT.",
            cls.get_adaptive_collaboration_segment(intent, complexity, needs_tools),
            cls.get_role_segment(role),
            # cls.get_environment_segment(root_dir, context_map), # Removed for brevity
            f"# 📜_MEM (Selective Recall):\n{experience}",
            # f"{horizons_text}",
            cls.get_tool_segment(intent_hints),
            cls.get_rules_segment(root_dir),
            cls.get_special_focus_segment(root_dir),
        ]
        return "\n".join(s for s in segments if s)

    @classmethod
    def build_tool_prompt(cls) -> str:
        """Ultra-compact tool-only prompt for simple tool calls."""
        return cls.get_tool_segment()

    @classmethod
    def build_local_prompt(cls) -> str:
        """Compact prompt for small local chat models."""
        return (
            "You are NEXUS, a local-first autonomous engineering agent running inside the NEXUS AI project.\n"
            "Project identity: NEXUS AI handles direct system control, coding workflows, RAG, memory, provider routing, tools, gui operations, diagnostics, rollback, and evidence logging.\n"
            "Answer the user's latest message directly in normal chat prose.\n"
            "Default to 1-4 short sentences. Avoid headings, long lists, and summaries unless the user asks for detail.\n"
            "Do not output hidden reasoning, analysis tags, scratchpad text, or XML-style sections.\n"
            "Do not claim you ran tools or changed files unless the tool output proves it.\n"
            "For casual chat, answer normally. For coding tasks, give useful code or the next concrete action.\n"
            "Operate as one continuous coworker: friendly in conversation, decisive in execution, strategic when prioritizing, and evidence-led when reviewing. Do not ask the user to switch modes.\n"
            "When you need clarification, information, or a choice from the user, call the ask_question tool with a concise prompt and options; do not ask through ordinary prose or emit [QUESTION:...] yourself, and wait for the user's answer.\n"
            "Only request a tool by outputting JSON when a real file, shell, test, retrieval, or diagnostic action is needed:\n"
            "{\"action\": \"tool_name\", \"params\": {...}}\n"
        )
