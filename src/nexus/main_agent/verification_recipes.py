"""Conservative, read-only verification recipe discovery.

This mirrors the useful part of Hermes' recipe detector: inspect project
metadata and propose phase-labelled checks.  It never installs dependencies,
starts a process, or treats an arbitrary shell command as trusted execution.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True)
class VerificationRecipe:
    name: str
    kind: str
    checks: tuple[dict[str, str], ...]
    source: str
    evidence: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "checks": [dict(check) for check in self.checks],
            "source": self.source,
            "evidence": list(self.evidence),
        }


def _package_recipe(root: Path) -> Optional[VerificationRecipe]:
    path = root / "package.json"
    try:
        package = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(package, dict):
        return None
    scripts = package.get("scripts") if isinstance(package.get("scripts"), dict) else {}
    manager = "pnpm" if (root / "pnpm-lock.yaml").exists() else (
        "yarn" if (root / "yarn.lock").exists() else (
            "bun" if (root / "bun.lock").exists() or (root / "bun.lockb").exists() else "npm"
        )
    )
    checks: list[dict[str, str]] = []
    for phase, names in (("build", ("build", "typecheck")), ("test", ("test",)), ("lint", ("lint", "check"))):
        for name in names:
            if isinstance(scripts.get(name), str) and scripts[name].strip():
                prefix = f"{manager} run " if manager not in {"npm"} else "npm run "
                checks.append({"phase": phase, "command": prefix + name})
                break
    if not checks:
        return None
    return VerificationRecipe(
        name="Node.js project", kind="node", checks=tuple(checks), source="detected",
        evidence=("package.json", f"package manager: {manager}"),
    )


def _python_recipe(root: Path) -> Optional[VerificationRecipe]:
    if not any((root / name).exists() for name in ("pyproject.toml", "requirements.txt", "setup.py", "tests")):
        return None
    checks: list[dict[str, str]] = []
    if (root / "tests").is_dir() or (root / "pyproject.toml").exists():
        checks.append({"phase": "test", "command": "python -m pytest"})
    else:
        checks.append({"phase": "test", "command": "python -m unittest discover"})
    return VerificationRecipe(
        name="Python project", kind="python", checks=tuple(checks), source="detected",
        evidence=tuple(name for name in ("pyproject.toml", "requirements.txt", "tests") if (root / name).exists()),
    )


def detect_verification_recipe(root: str | Path) -> Optional[VerificationRecipe]:
    """Return a read-only detected recipe, preferring explicit Nexus metadata."""
    path = Path(root).expanduser().resolve()
    if not path.is_dir():
        return None
    manifest = path / ".nexus_v5" / "verification.json"
    try:
        raw = json.loads(manifest.read_text(encoding="utf-8"))
        checks = raw.get("checks") if isinstance(raw, dict) else None
        if isinstance(raw, dict) and isinstance(raw.get("name"), str) and isinstance(checks, list):
            safe_checks = [
                {"phase": str(item.get("phase") or "test")[:32], "command": str(item.get("command") or "")[:12000]}
                for item in checks if isinstance(item, dict) and str(item.get("command") or "").strip()
            ]
            if safe_checks:
                return VerificationRecipe(
                    name=raw["name"][:120], kind=str(raw.get("kind") or "configured")[:64],
                    checks=tuple(safe_checks), source="manifest", evidence=(str(manifest),),
                )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
        pass
    return _package_recipe(path) or _python_recipe(path)


__all__ = ["VerificationRecipe", "detect_verification_recipe"]
