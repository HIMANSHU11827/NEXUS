"""NexusResearcher — local, evidence-gathering research.

This is an honest, local-only research agent. It NEVER calls an LLM. It
keyword-scans the repository (``docs/``, ``skills/``, ``tools/`` metadata) for
on-disk evidence that matches a topic, scores each candidate document, and
synthesizes a brief summary from what it actually finds. If nothing matches it
says so — it never fabricates findings.
"""

from __future__ import annotations

__version__ = "0.2.0"

import json
import logging
import os
import re
from typing import Any, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)

IS_STUB = False

#: Basic stopwords filtered out of a topic so scoring focuses on real terms.
_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "not", "no", "is", "are", "am", "was",
    "were", "be", "been", "being", "do", "does", "did", "how", "what", "why",
    "which", "who", "whom", "that", "when", "where", "of", "to", "for", "with",
    "by", "on", "at", "in", "from", "as", "it", "its", "this", "those",
    "these", "can", "could", "should", "would", "will", "may", "might", "must",
    "please", "tell", "about", "about", "into", "help",
})

_MAX_SCAN_FILES = 400
_MAX_READ_CHARS = 4000
_MAX_FINDINGS = 8


class NexusResearcher:
    """Keyword-scans the repo for on-disk evidence about a topic."""

    is_stub = False

    def __init__(self, root: str) -> None:
        self.root = os.path.abspath(root.rstrip("/\\"))

    # ── Public API ─────────────────────────────────────────────────────

    def research(self, topic: str, **kwargs: Any) -> Dict[str, Any]:
        """Gather local evidence for a topic; returns findings/sources/summary."""
        keywords = _keywords(topic)
        findings = self._gather(
            keywords,
            max_findings=int(kwargs.get("max_findings", _MAX_FINDINGS)),
        )
        sources = [
            {"kind": f["kind"], "name": f["name"], "path": f["path"]}
            for f in findings
        ]
        return {
            "status": "ok",
            "topic": topic,
            "findings": findings,
            "sources": sources,
            "summary": (
                _synthesize_summary(topic, findings)
                if findings
                else f"No local evidence found for {topic!r}. Try a more specific topic."
            ),
        }

    def investigate(self, question: str, **kwargs: Any) -> Dict[str, Any]:
        """A research() run framed as a question; same evidence pipeline."""
        result = self.research(question, **kwargs)
        result["question"] = question
        return result

    def status(self) -> Dict[str, Any]:
        return {
            "status": "ok",
            "is_stub": False,
            "module": "NexusResearcher",
            "mode": "local_evidence_scan",
            "llm": False,
            "root": self.root,
            "scoped_dirs": ["docs", "skills", "tools"],
            "method": "keyword scoring over on-disk docs and metadata",
        }

    # ── Internals ──────────────────────────────────────────────────────

    def _gather(self, keywords: List[str], max_findings: int) -> List[Dict[str, Any]]:
        patterns = [_pattern(k) for k in keywords]
        scored: List[Dict[str, Any]] = []
        scanned = 0
        for kind, path, text in self._iter_candidates():
            scanned += 1
            if scanned > _MAX_SCAN_FILES:
                break
            if not patterns or not text:
                continue
            matched = [k for k, p in zip(keywords, patterns) if p and p.search(text)]
            if not matched:
                continue
            score = len(matched) * 10 + min(len(text) // 1000, 5)
            name, description = _describe(kind, path)
            scored.append({
                "kind": kind,
                "name": name,
                "path": path,
                "relative_path": os.path.relpath(path, self.root).replace("\\", "/"),
                "description": description[:200],
                "score": score,
                "matched_terms": matched,
            })
        scored.sort(key=lambda entry: entry["score"], reverse=True)
        return scored[:max_findings]

    def _iter_candidates(self) -> Iterator[Tuple[str, str, str]]:
        base = self.root
        docs_dir = os.path.join(base, "docs")
        if os.path.isdir(docs_dir):
            for path in _walk_md(docs_dir):
                yield "doc", path, _read(path)
        skills_dir = os.path.join(base, "skills")
        if os.path.isdir(skills_dir):
            for path in _walk_md(skills_dir, only_skill_md=True):
                text = _read(path)
                if text:
                    # Include the relative path so a topic like "skills" can
                    # match its own corpus, not just body prose.
                    text = os.path.relpath(path, base) + "\n" + text
                yield "skill", path, text
        tools_dir = os.path.join(base, "tools")
        if os.path.isdir(tools_dir):
            for path in _walk_tool_meta(tools_dir):
                text = _read(path)
                if text:
                    text = os.path.relpath(path, base) + "\n" + text
                yield "tool", path, text


def _keywords(topic: str) -> List[str]:
    words = re.split(r"[^a-z0-9]+", str(topic or "").lower())
    return [w for w in words if len(w) > 1 and w not in _STOPWORDS]


def _pattern(word: str) -> Optional[re.Pattern]:
    try:
        return re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)
    except re.error:
        return None


def _walk_md(start_dir: str, only_skill_md: bool = False) -> Iterator[str]:
    for dirpath, dirnames, filenames in os.walk(start_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith((".", "_"))]
        for fname in filenames:
            if not fname.endswith(".md"):
                continue
            if only_skill_md and fname.lower() != "skill.md":
                continue
            yield os.path.join(dirpath, fname)


def _walk_tool_meta(tools_dir: str) -> Iterator[str]:
    for name in sorted(os.listdir(tools_dir)):
        if name.startswith((".", "_")) or name == "nexus_tools":
            continue
        tool_dir = os.path.join(tools_dir, name)
        if not os.path.isdir(tool_dir):
            continue
        for ext in (".jsnol", ".json"):
            meta_path = os.path.join(tool_dir, name + ext)
            if os.path.isfile(meta_path):
                yield meta_path
                break


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            return handle.read(_MAX_READ_CHARS)
    except OSError:
        return ""


def _describe(kind: str, path: str) -> Tuple[str, str]:
    if kind == "skill":
        name = os.path.basename(os.path.dirname(path))
        description = _frontmatter_field(_read(path), "description") or _first_line(_read(path))
    elif kind == "tool":
        name = os.path.splitext(os.path.basename(path))[0]
        description = _tool_description(_read(path))
    else:
        name = os.path.basename(path)
        description = _first_line(_read(path))
    return name, description or ""


def _tool_description(text: str) -> str:
    try:
        meta = json.loads(text)
        if isinstance(meta, dict) and meta.get("description"):
            return str(meta["description"])[:200]
    except Exception:
        pass
    return _first_line(text)


def _frontmatter_field(text: str, field: str) -> Optional[str]:
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    for line in text[3:end].splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            if key.strip().lower() == field:
                return value.strip().strip('"').strip("'") or None
    return None


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:200]
    return ""


def _synthesize_summary(topic: str, findings: List[Dict[str, Any]]) -> str:
    grouped: Dict[str, List[str]] = {}
    for finding in findings:
        grouped.setdefault(finding["kind"], []).append(finding["name"])
    parts = []
    for kind in ("skill", "tool", "doc"):
        if kind in grouped:
            parts.append(f"{len(grouped[kind])} {kind}(s): {', '.join(grouped[kind][:4])}")
    lead = findings[0]
    return (
        f"Found {len(findings)} local matches for {topic!r} across "
        f"{'; '.join(parts) if parts else 'the repository'}. "
        f"Strongest match: {lead['name']} ({lead['kind']})."
    )
