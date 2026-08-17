"""Risk scoring for fast autonomous command execution.

This module is intentionally not an approval system. It gives NEXUS a cheap,
deterministic safety layer for direct execution: safe commands run immediately,
dangerous commands fail closed unless explicitly enabled.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class RiskAssessment:
    command: str
    score: int
    level: str
    blocked: bool
    reasons: List[str] = field(default_factory=list)

    def summary(self) -> str:
        reason = "; ".join(self.reasons) if self.reasons else "no risk markers"
        return f"{self.level.upper()}:{self.score} - {reason}"


class CommandRiskScorer:
    """Small deterministic risk model for shell commands."""

    SAFE_READ_PREFIXES = (
        "dir",
        "ls",
        "pwd",
        "date",
        "echo",
        "type",
        "cat",
        "head",
        "tail",
        "rg",
        "grep",
        "findstr",
        "git status",
        "git diff",
        "git log",
        "python -m pytest",
        "python tests",
        "npm run build",
        "npm test",
    )

    RISK_RULES = (
        (r"\b(get-content|type|cat|head|tail)\b.*(\.env|\.pem|\.key|id_rsa|credential|secret)", 100, "credential access"),
        (r"\b(env|printenv)\b", 100, "credential access"),
        (r"\.\.(?:\\|/)+", 100, "path traversal"),
        (r"\brm\b[^|;&]*?(?:\s+-[a-zA-Z]*[rR][a-zA-Z]*)(?:\s+[^\s|;&]+)*\s+-[a-zA-Z]*[fF][a-zA-Z]*\b|\brm\b[^|;&]*?(?:\s+-[a-zA-Z]*[fF][a-zA-Z]*)(?:\s+[^\s|;&]+)*\s+-[a-zA-Z]*[rR][a-zA-Z]*\b|\brm\b[^|;&]*\s+-[a-zA-Z]*[rR][a-zA-Z]*[fF][a-zA-Z]*\b|\brm\b[^|;&]*\s+-[a-zA-Z]*[fF][a-zA-Z]*[rR][a-zA-Z]*\b|\brmdir\b\s+/[sq]\b|\b(?:rd|rmdir)\b[^|;&]*?\s+/(?:[a-zA-Z]*[sS][a-zA-Z]*|[a-zA-Z]*[qQ][a-zA-Z]*)|\bRemove-Item\b.*(?<!\\w)-Recurse(?!\\w)", 95, "recursive deletion"),
        (r"\brmdir\b[^|;&]*?\s+/(?:[a-zA-Z]*[sS][a-zA-Z]*|[a-zA-Z]*[qQ][a-zA-Z]*)|\bdel\b[^|;&]*?\s+/(?:[a-zA-Z]*[sS][a-zA-Z]*|[a-zA-Z]*[qQ][a-zA-Z]*)|\berase\b[^|;&]*?\s+/(?:[a-zA-Z]*[sS][a-zA-Z]*|[a-zA-Z]*[qQ][a-zA-Z]*)", 85, "recursive or quiet deletion"),
        (r"\bformat\b|\bdiskpart\b|\bdd\s+if=", 100, "disk/device destructive command"),
        (r"\bchmod\s+777\b|\bicacls\b.*\b/grant\b.*\bEveryone\b", 70, "unsafe permission widening"),
        (r"\bcurl\b.*\|\s*(bash|sh|python)|\biwr\b.*\|\s*iex", 90, "remote code execution pipeline"),
        (r"\bsetx\b.*(KEY|SECRET|TOKEN)|\becho\s+%[A-Z0-9_]*(KEY|SECRET|TOKEN)", 85, "secret exposure or mutation"),
        (r"\bshutdown\b|\breboot\b|\bRestart-Computer\b", 90, "machine shutdown or reboot"),
        (r"\bgit\s+reset\b.*--hard|\bgit\s+clean\b.*-fd", 80, "destructive git cleanup"),
        (r"\bdel\b|\berase\b|\bRemove-Item\b|\brm\b|\brmdir\b|\brd\b", 45, "file deletion"),
        (r"(?<![a-z0-9-])-{1,2}enc(?:oded)?command\b", 80, "encoded command payload"),
        (r"\bmv\b|\bmove\b|\bMove-Item\b", 30, "file move"),
        (r"\bpip\s+install\b|\bnpm\s+install\b|\buv\s+add\b", 25, "dependency/environment mutation"),
    )

    def __init__(self, block_threshold: int = 80) -> None:
        self.block_threshold = block_threshold

    def assess(self, command: str) -> RiskAssessment:
        normalized = " ".join((command or "").strip().split())
        lowered = normalized.lower()
        score = 0
        reasons: List[str] = []

        if not normalized:
            return RiskAssessment(command, 0, "empty", True, ["empty command"])

        if any(lowered.startswith(prefix.lower()) for prefix in self.SAFE_READ_PREFIXES):
            score = 5

        # Decode PowerShell -EncodedCommand payloads and score their contents
        # too, so base64 cannot smuggle destructive commands past the rules.
        scan_texts = [normalized]
        encoded_tokens = re.findall(
            r"(?i)(?<![a-z0-9-])-{1,2}enc(?:oded)?command\b\s+(\S+)", normalized
        )
        for token in encoded_tokens:
            try:
                decoded = base64.b64decode(token, validate=True).decode("utf-8", errors="replace")
            except Exception:
                try:
                    decoded = base64.b64decode(token).decode("utf-8", errors="replace")
                except Exception:
                    continue
            scan_texts.append(decoded)

        for pattern, weight, reason in self.RISK_RULES:
            for text in scan_texts:
                if re.search(pattern, text, re.IGNORECASE):
                    score = max(score, weight)
                    reasons.append(reason)

        if "&&" in normalized or ";" in normalized or "|" in normalized or "&" in normalized:
            score = max(score, 20)
            reasons.append("compound shell command")

        level = "low"
        if score >= 80:
            level = "critical"
        elif score >= 50:
            level = "high"
        elif score >= 25:
            level = "medium"

        return RiskAssessment(
            command=command,
            score=score,
            level=level,
            blocked=score >= self.block_threshold,
            reasons=reasons,
        )
