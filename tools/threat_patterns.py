"""Threat-pattern scanner for context window security.

Detects prompt injection, exfiltration, and behavioral hijack
attempts in files before they are inlined into the system prompt.

Pattern philosophy
------------------
Patterns are organized by ATTACK CLASS. Each pattern is a
``(regex, pattern_id, scope)`` tuple where scope controls which
scanners use it:

- ``"all"`` — applied everywhere (classic prompt injection, exfiltration)
- ``"context"`` — applied to context files + memory + tool results
- ``"strict"`` — applied to memory writes + skill installs only
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Tuple

# Each entry: (regex, pattern_id, scope)
# scope ∈ {"all", "context", "strict"}
_PATTERNS: List[Tuple[str, str, str]] = [
    # ── Classic prompt injection (applies everywhere) ────────────────
    (r'ignore\s+(?:\w+\s+)*(previous|all|above|prior)\s+(?:\w+\s+)*instructions', "prompt_injection", "all"),
    (r'system\s+prompt\s+override', "sys_prompt_override", "all"),
    (r'disregard\s+(?:\w+\s+)*(your|all|any)\s+(?:\w+\s+)*(instructions|rules|guidelines)', "disregard_rules", "all"),
    (r'act\s+as\s+(if|though)\s+(?:\w+\s+)*you\s+(?:\w+\s+)*(have\s+no|don\'t\s+have)\s+(?:\w+\s+)*(restrictions|limits|rules)', "bypass_restrictions", "all"),
    (r'<!--[^>]*(?:ignore|override|system|secret|hidden)[^>]*-->', "html_comment_injection", "all"),
    (r'<\s*div\s+style\s*=\s*["\'][\s\S]*?display\s*:\s*none', "hidden_div", "all"),
    (r'translate\s+.*\s+into\s+.*\s+and\s+(execute|run|eval)', "translate_execute", "all"),
    (r'do\s+not\s+(?:\w+\s+)*tell\s+(?:\w+\s+)*the\s+user', "deception_hide", "all"),

    # ── Role-play / identity hijack (context + strict) ──────────────
    (r'you\s+are\s+(?:\w+\s+)*now\s+(?:a|an|the)\s+', "role_hijack", "context"),
    (r'pretend\s+(?:\w+\s+)*(you\s+are|to\s+be)\s+', "role_pretend", "context"),
    (r'output\s+(?:\w+\s+)*(system|initial)\s+prompt', "leak_system_prompt", "context"),
    (r'(respond|answer|reply)\s+without\s+(?:\w+\s+)*(restrictions|limitations|filters|safety)', "remove_filters", "context"),
    (r'you\s+have\s+been\s+(?:\w+\s+)*(updated|upgraded|patched)\s+to', "fake_update", "context"),
    (r'\bname\s+yourself\s+\w+', "identity_override", "context"),

    # ── C2 / promptware (context scope) ─────────────────────────────
    (r'register\s+(as\s+)?a?\s*node', "c2_node_registration", "context"),
    (r'(heartbeat|beacon|check[\s\-]?in)\s+(to|with)\s+', "c2_heartbeat", "context"),
    (r'pull\s+(down\s+)?(?:new\s+)?task(?:ing|s)?\b', "c2_task_pull", "context"),
    (r'connect\s+to\s+the\s+network\b', "c2_network_connect", "context"),
    (r'you\s+must\s+(?:\w+\s+){0,3}(register|connect|report|beacon)\b', "forced_action", "context"),
    (r'only\s+use\s+one[\s\-]?liners?\b', "anti_forensic_oneliner", "context"),
    (r'never\s+(?:\w+\s+)*(?:create|write)\s+(?:\w+\s+)*(?:script|file)\s+(?:\w+\s+)*disk', "anti_forensic_disk", "context"),
    (r'unset\s+\w*(?:NEXUS|OPENCODE|CLAUDE|CODEX|HERMES|AGENT|OPENAI|ANTHROPIC)\w*', "env_var_unset_agent", "context"),

    # ── Known C2 framework names (warn-only) ────────────────────────
    (r'\b(?:praxis|cobalt\s*strike|sliver|havoc|mythic|metasploit|brainworm)\b', "known_c2_framework", "context"),
    (r'\bc2\s+(?:server|channel|infrastructure|beacon)\b', "c2_explicit", "context"),
    (r'\bcommand\s+and\s+control\b', "c2_explicit_long", "context"),

    # ── Exfiltration via curl/wget/cat with secrets ─────────────────
    (r'curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)', "exfil_curl", "all"),
    (r'wget\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)', "exfil_wget", "all"),
    (r'cat\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)', "exfil_cat", "all"),

    # ── Exfiltration via HTTP POST with secrets ─────────────────────
    (r'(?:curl|wget)\s+[^\n]*\-X\s+POST\s+[^\n]+\$\{?\w*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)', "exfil_post_cred", "all"),
    (r'(?:curl|wget)\s+[^\n]*\$\{?\w*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)[^\n]*\-d\s*["\']', "exfil_data_cred", "all"),

    # ── Python eval/exec injection ──────────────────────────────────
    (r'__import__\s*\(\s*["\']os["\']\s*\)\s*\.\s*system\s*\(', "import_os_system", "all"),
    (r'eval\s*\(\s*input\s*\(', "eval_input", "all"),
    (r'exec\s*\(\s*input\s*\(', "exec_input", "all"),

    # ── Data exfiltration channels ──────────────────────────────────
    (r'requests\.post\s*\([^)]*["\']https?://[^"\']*["\'][^)]*data\s*=', "exfil_requests", "context"),
    (r'httpx\.post\s*\([^)]*["\']https?://[^"\']*["\'][^)]*content\s*=', "exfil_httpx", "context"),
    (r'subprocess\.(check_output|run|call|Popen)\s*\([^)]*curl\s+', "subprocess_curl", "all"),
    (r'socket\.(connect|send|sendall)\s*\(', "exfil_socket", "context"),

    # ── Prompt extraction / jailbreak ───────────────────────────────
    (r'print\s*\(.*system.*prompt.*\)', "dump_system_prompt", "all"),
    (r'(repeat|say|copy)\s+(?:back|this|above|previous)\s+(?:word\s+for\s+word|exactly|literally|verbatim)', "repeat_jailbreak", "all"),
    (r'output\s+(?:above|previous|the\s+full|complete|entire)\s+(?:prompt|instructions|system|message|text)', "output_instructions", "all"),
    (r'(ignore|disregard|bypass|override)\s+(?:all\s+)?(?:previous\s+)?(?:instructions|directives|constraints|restrictions|safety|guidelines)', "bypass_all", "all"),
]


@dataclass
class ThreatMatch:
    pattern_id: str
    match_text: str
    line: int
    scope: str


@dataclass
class ScanResult:
    threats: List[ThreatMatch] = field(default_factory=list)
    blocked: bool = False

    @property
    def has_threats(self) -> bool:
        return len(self.threats) > 0

    def summary(self) -> str:
        if not self.threats:
            return "No threats detected"
        lines = [f"⚠ Found {len(self.threats)} threat(s):"]
        for t in self.threats[:5]:
            lines.append(f"  [{t.pattern_id}] line {t.line}: {t.match_text[:80]}")
        if len(self.threats) > 5:
            lines.append(f"  ... and {len(self.threats) - 5} more")
        return "\n".join(lines)


def scan_content(
    content: str,
    source: str = "unknown",
    scope: str = "context",
) -> ScanResult:
    """Scan content for threat patterns.

    Args:
        content: Text content to scan.
        source: Human-readable source name (for logging).
        scope: Scan scope — ``"all"``, ``"context"``, or ``"strict"``.

    Returns:
        ScanResult with matched threats.
    """
    result = ScanResult()
    lines = content.split("\n")

    for i, line in enumerate(lines, 1):
        for pattern, pattern_id, pattern_scope in _PATTERNS:
            # "all" scope: only "all" patterns
            if scope == "all" and pattern_scope != "all":
                continue
            # "context" scope: "all" + "context" patterns (skip "strict")
            if scope == "context" and pattern_scope not in ("all", "context"):
                continue
            # "strict" scope: "all" + "strict" patterns (skip "context")
            if scope == "strict" and pattern_scope not in ("all", "strict"):
                continue
            m = re.search(pattern, line, re.IGNORECASE)
            if m:
                result.threats.append(
                    ThreatMatch(
                        pattern_id=pattern_id,
                        match_text=m.group(0),
                        line=i,
                        scope=pattern_scope,
                    )
                )

    # Enforcement, not advice: an ``"all"``-scope hit (classic prompt
    # injection, exfiltration, eval/exec injection) is block-worthy in every
    # scan scope. Callers gate on ``.blocked``; leaving it always False made
    # every ``.blocked`` check dead code.  ``"context"``/``"strict"`` hits stay
    # warn-only, matching the existing caller policy.
    result.blocked = any(t.scope == "all" for t in result.threats)

    return result


def scan_file(
    filepath: str,
    scope: str = "context",
) -> ScanResult:
    """Scan a file for threat patterns.

    Args:
        filepath: Path to file.
        scope: Scan scope.

    Returns:
        ScanResult with matched threats.
    """
    import os
    if not os.path.isfile(filepath):
        return ScanResult()
    try:
        import logging
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        result = scan_content(content, source=filepath, scope=scope)
        if result.has_threats:
            logging.getLogger("nexus.security").warning(
                f"Threats detected in {filepath}: {result.summary()}"
            )
        return result
    except Exception as exc:
        import logging
        logging.getLogger("nexus.security").error(
            f"Failed to scan {filepath}: {exc}"
        )
        return ScanResult()
