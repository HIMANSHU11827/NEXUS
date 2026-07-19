from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


def _safe_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(value or "").strip())
    return safe[:120] or "default"


@dataclass
class RunContext:
    """Durable identity and terminal status for a single agent run."""

    run_id: str
    session_id: str
    root: str
    provider: str = ""
    model: str = ""
    max_tokens: Optional[int] = None
    voice_mode: bool = False
    status: str = "running"
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    terminal_event: str = ""
    error: str = ""
    prompt_preview: str = ""

    @property
    def path(self) -> str:
        return run_context_path(self.root, self.session_id, self.run_id)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def persist(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        payload = self.to_dict()
        temporary = f"{self.path}.{os.getpid()}.{int(time.time() * 1000)}.tmp"
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)

    def finish(self, status: str, terminal_event: str, error: str = "") -> None:
        now = time.time()
        self.status = status
        self.terminal_event = terminal_event
        self.error = str(error or "")[:1000]
        self.updated_at = now
        self.completed_at = now
        self.persist()


def run_context_path(root: str, session_id: str, run_id: str) -> str:
    return os.path.join(
        os.path.abspath(root),
        "logs",
        "run_contexts",
        _safe_id(session_id),
        f"{_safe_id(run_id)}.json",
    )


def start_run_context(
    *,
    root: str,
    session_id: str,
    run_id: str,
    prompt: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    voice_mode: bool = False,
) -> RunContext:
    context = RunContext(
        root=os.path.abspath(root),
        session_id=_safe_id(session_id),
        run_id=_safe_id(run_id),
        provider=str(provider or ""),
        model=str(model or ""),
        max_tokens=max_tokens,
        voice_mode=voice_mode,
        prompt_preview=str(prompt or "").strip().replace("\r", " ").replace("\n", " ")[:240],
    )
    context.persist()
    return context


def load_run_context(root: str, session_id: str, run_id: str) -> Optional[Dict[str, Any]]:
    path = run_context_path(root, session_id, run_id)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        return loaded if isinstance(loaded, dict) else None
    except FileNotFoundError:
        return None


def list_run_contexts(root: str, session_id: str = "", limit: int = 100) -> List[Dict[str, Any]]:
    base = os.path.join(os.path.abspath(root), "logs", "run_contexts")
    roots = []
    if session_id:
        roots.append(os.path.join(base, _safe_id(session_id)))
    elif os.path.isdir(base):
        roots.extend(
            os.path.join(base, name)
            for name in os.listdir(base)
            if os.path.isdir(os.path.join(base, name))
        )
    contexts: List[Dict[str, Any]] = []
    for folder in roots:
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            if not name.endswith(".json"):
                continue
            path = os.path.join(folder, name)
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                if isinstance(loaded, dict):
                    loaded["_path"] = path
                    contexts.append(loaded)
            except (OSError, json.JSONDecodeError):
                continue
    contexts.sort(key=lambda item: float(item.get("updated_at") or item.get("started_at") or 0), reverse=True)
    return contexts[: max(1, min(int(limit or 100), 1000))]
