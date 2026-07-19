"""SkillCurator — background skill lifecycle manager for NEXUS AI."""
__version__ = "1.0.0"

import json
import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

USAGE_FILE = "workspace/skill_usage.json"
ARCHIVE_DIR = "skills/.archive"
SKILLS_DIR = "skills"
STALE_AFTER_DAYS = 30
ARCHIVE_AFTER_DAYS = 90
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


class SkillCurator:
    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)
        self.skills_dir = os.path.join(self.root, SKILLS_DIR)
        self.archive_dir = os.path.join(self.root, ARCHIVE_DIR)
        self.usage_file = os.path.join(self.root, USAGE_FILE)
        self.stale_after_days = STALE_AFTER_DAYS
        self.archive_after_days = ARCHIVE_AFTER_DAYS
        self.enabled = True
        self._usage_cache: Dict[str, Dict[str, Any]] = {}
        self._last_run: Optional[float] = None
        self._load_usage()

    # ── Config ───────────────────────────────────────────────────────────────

    def set_config(
        self,
        stale_after_days: Optional[int] = None,
        archive_after_days: Optional[int] = None,
        enabled: Optional[bool] = None,
    ) -> Dict[str, Any]:
        if stale_after_days is not None:
            self.stale_after_days = max(1, stale_after_days)
        if archive_after_days is not None:
            self.archive_after_days = max(1, archive_after_days)
        if enabled is not None:
            self.enabled = bool(enabled)
        logger.info(
            f"[CURATOR] Config: stale={self.stale_after_days}d, "
            f"archive={self.archive_after_days}d, enabled={self.enabled}"
        )
        return self.get_stats()

    # ── Usage Tracking ──────────────────────────────────────────────────────

    def _load_usage(self) -> None:
        try:
            if os.path.isfile(self.usage_file):
                with open(self.usage_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._usage_cache = data if isinstance(data, dict) else {}
            else:
                self._usage_cache = {}
                self._save_usage()
        except (json.JSONDecodeError, OSError):
            self._usage_cache = {}

    def _save_usage(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.usage_file), exist_ok=True)
            with open(self.usage_file, "w", encoding="utf-8") as f:
                json.dump(self._usage_cache, f, indent=2, default=str)
        except OSError as e:
            logger.error(f"[CURATOR] Failed to save usage: {e}")

    def _get_usage(self, name: str) -> Dict[str, Any]:
        return self._usage_cache.get(name, {
            "use_count": 0,
            "last_activity_at": None,
            "state": "active",
        })

    def _set_usage(self, name: str, data: Dict[str, Any]) -> None:
        self._usage_cache[name] = data
        self._save_usage()

    def record_use(self, name: str) -> Dict[str, Any]:
        usage = self._get_usage(name)
        usage["use_count"] = usage.get("use_count", 0) + 1
        usage["last_activity_at"] = time.time()
        if usage.get("state") not in ("pinned",):
            usage["state"] = "active"
        self._set_usage(name, usage)
        return usage

    # ── Skill Discovery ──────────────────────────────────────────────────────

    def _list_skill_dirs(self) -> List[Path]:
        skills_path = Path(self.skills_dir)
        if not skills_path.is_dir():
            return []
        return sorted(
            p for p in skills_path.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )

    def _list_md_skills(self) -> List[Path]:
        skills_path = Path(self.skills_dir)
        if not skills_path.is_dir():
            return []
        return sorted(p for p in skills_path.iterdir() if p.suffix == ".md")

    def _parse_frontmatter(self, md_path: Path) -> Dict[str, Any]:
        try:
            content = md_path.read_text(encoding="utf-8")
            m = FRONTMATTER_RE.match(content)
            if not m:
                return {}
            meta: Dict[str, Any] = {}
            for line in m.group(1).split("\n"):
                if ":" in line:
                    key, _, val = line.partition(":")
                    meta[key.strip()] = val.strip()
            return meta
        except Exception:
            return {}

    def _is_pinned(self, name: str) -> bool:
        fm = self._read_frontmatter(name)
        if fm and str(fm.get("pinned", "")).lower() == "true":
            return True
        usage = self._get_usage(name)
        return usage.get("state") == "pinned"

    def _read_frontmatter(self, name: str) -> Dict[str, Any]:
        md_path = Path(self.skills_dir) / name / "SKILL.md"
        if md_path.is_file():
            return self._parse_frontmatter(md_path)
        md_path = Path(self.skills_dir) / f"{name}.md"
        if md_path.is_file():
            return self._parse_frontmatter(md_path)
        return {}

    # ── Core Methods ─────────────────────────────────────────────────────────

    def run_once(self) -> Dict[str, Any]:
        if not self.enabled:
            return {"status": "disabled", "archived": 0, "restored": 0}

        self._load_usage()
        now = time.time()
        archived = 0
        restored = 0
        results: List[Dict[str, Any]] = []

        all_skills = self._discover_all_skills()

        for name, source in all_skills:
            usage = self._get_usage(name)

            if usage.get("state") == "pinned":
                continue

            if self._is_pinned_after_discovery(name):
                continue

            last_active = usage.get("last_activity_at")
            state = usage.get("state", "active")

            if state == "active" and last_active is not None:
                days_since = (now - float(last_active)) / 86400
                if days_since > self.stale_after_days:
                    result = self.archive_skill(name)
                    if result.get("success"):
                        archived += 1
                        results.append(result)

        self._last_run = now
        self._save_usage()
        return {
            "status": "ok",
            "archived": archived,
            "restored": restored,
            "results": results,
        }

    def _discover_all_skills(self) -> List[Tuple[str, str]]:
        skills: List[Tuple[str, str]] = []
        for d in self._list_skill_dirs():
            skills.append((d.name, "dir"))
        for f in self._list_md_skills():
            skills.append((f.stem, "md"))
        return skills

    def _is_pinned_after_discovery(self, name: str) -> bool:
        fm = self._read_frontmatter(name)
        if fm and str(fm.get("pinned", "")).lower() == "true":
            self._set_usage(name, {
                **self._get_usage(name),
                "state": "pinned",
            })
            return True
        return False

    def archive_skill(self, name: str) -> Dict[str, Any]:
        name_clean = name.strip().lower().replace(" ", "-")
        usage = self._get_usage(name_clean)

        if usage.get("state") == "pinned":
            return {
                "success": False,
                "name": name_clean,
                "error": "skill is pinned",
            }

        source_dir = Path(self.skills_dir) / name_clean
        source_md = Path(self.skills_dir) / f"{name_clean}.md"
        archive_target = Path(self.archive_dir) / name_clean

        try:
            os.makedirs(str(archive_target), exist_ok=True)
            moved = False

            if source_dir.is_dir():
                for item in source_dir.iterdir():
                    dest = archive_target / item.name
                    shutil.move(str(item), str(dest))
                try:
                    source_dir.rmdir()
                except OSError:
                    logger.warning("evolution/curator/scripts/curator.py:232 suppressed error", exc_info=True)
                moved = True

            if source_md.is_file():
                dest = archive_target / source_md.name
                shutil.move(str(source_md), str(dest))
                moved = True

            if not moved:
                return {
                    "success": False,
                    "name": name_clean,
                    "error": f"skill '{name_clean}' not found",
                }

            self._last_activity(name_clean)
            usage["state"] = "archived"
            self._set_usage(name_clean, usage)
            logger.info(f"[CURATOR] Archived skill '{name_clean}'")
            return {
                "success": True,
                "name": name_clean,
                "action": "archived",
                "path": str(archive_target),
            }

        except OSError as e:
            logger.error(f"[CURATOR] Failed to archive '{name_clean}': {e}")
            return {"success": False, "name": name_clean, "error": str(e)}

    def restore_skill(self, name: str) -> Dict[str, Any]:
        name_clean = name.strip().lower().replace(" ", "-")
        archive_path = Path(self.archive_dir) / name_clean
        skills_path = Path(self.skills_dir)

        if not archive_path.is_dir():
            return {
                "success": False,
                "name": name_clean,
                "error": f"archived skill '{name_clean}' not found",
            }

        try:
            target = skills_path / name_clean
            os.makedirs(str(target), exist_ok=True)

            for item in archive_path.iterdir():
                dest = target / item.name
                shutil.move(str(item), str(dest))

            try:
                archive_path.rmdir()
            except OSError:
                logger.warning("evolution/curator/scripts/curator.py:285 suppressed error", exc_info=True)

            self._last_activity(name_clean)
            usage = self._get_usage(name_clean)
            usage["state"] = "active"
            self._set_usage(name_clean, usage)
            logger.info(f"[CURATOR] Restored skill '{name_clean}'")
            return {
                "success": True,
                "name": name_clean,
                "action": "restored",
                "path": str(target),
            }

        except OSError as e:
            logger.error(f"[CURATOR] Failed to restore '{name_clean}': {e}")
            return {"success": False, "name": name_clean, "error": str(e)}

    def pin_skill(self, name: str) -> Dict[str, Any]:
        name_clean = name.strip().lower().replace(" ", "-")
        usage = self._get_usage(name_clean)
        usage["state"] = "pinned"
        self._set_usage(name_clean, usage)

        self._update_frontmatter_pin(name_clean, True)
        logger.info(f"[CURATOR] Pinned skill '{name_clean}'")
        return {"success": True, "name": name_clean, "action": "pinned"}

    def unpin_skill(self, name: str) -> Dict[str, Any]:
        name_clean = name.strip().lower().replace(" ", "-")
        usage = self._get_usage(name_clean)
        usage["state"] = "active"
        self._set_usage(name_clean, usage)

        self._update_frontmatter_pin(name_clean, False)
        logger.info(f"[CURATOR] Unpinned skill '{name_clean}'")
        return {"success": True, "name": name_clean, "action": "unpinned"}

    def _update_frontmatter_pin(self, name: str, pinned: bool) -> None:
        md_path = Path(self.skills_dir) / name / "SKILL.md"
        if not md_path.is_file():
            md_path = Path(self.skills_dir) / f"{name}.md"
        if not md_path.is_file():
            md_path = Path(self.archive_dir) / name / "SKILL.md"
        if not md_path.is_file():
            md_path = Path(self.archive_dir) / f"{name}.md"
        if not md_path.is_file():
            return

        try:
            content = md_path.read_text(encoding="utf-8")
            m = FRONTMATTER_RE.match(content)
            if m:
                fm_text = m.group(1)
                if re.search(r"^pinned:", fm_text, re.MULTILINE):
                    new_fm = re.sub(
                        r"^pinned:\s*\S+",
                        f"pinned: {str(pinned).lower()}",
                        fm_text,
                        flags=re.MULTILINE,
                    )
                else:
                    new_fm = fm_text + f"\npinned: {str(pinned).lower()}"
                new_content = content.replace(fm_text, new_fm, 1)
                md_path.write_text(new_content, encoding="utf-8")
        except Exception as e:
            logger.debug(f"[CURATOR] Frontmatter pin update failed for '{name}': {e}")

    def list_skills(self, state: Optional[str] = None) -> List[Dict[str, Any]]:
        self._load_usage()
        results: List[Dict[str, Any]] = []
        all_skills = self._discover_all_skills()

        for name, source_type in all_skills:
            usage = self._get_usage(name)
            us = usage.get("state", "active")

            fm = self._read_frontmatter(name)
            desc = fm.get("description", "")

            entry = {
                "name": name,
                "source": source_type,
                "state": us,
                "pinned": self._is_pinned(name),
                "description": desc,
                "use_count": usage.get("use_count", 0),
                "last_activity_at": usage.get("last_activity_at"),
            }
            results.append(entry)

        if state:
            results = [r for r in results if r["state"] == state]

        return sorted(results, key=lambda x: x["name"])

    def get_stats(self) -> Dict[str, Any]:
        self._load_usage()
        now = time.time()

        all_skills = self._discover_all_skills()
        total = len(all_skills)
        pinned = sum(1 for n, _ in all_skills if self._is_pinned(n))

        active = 0
        archived = 0
        stale = 0
        for name, _ in all_skills:
            usage = self._get_usage(name)
            us = usage.get("state", "active")
            if us == "archived":
                archived += 1
            elif us == "pinned":
                pass
            else:
                active += 1
            last_active = usage.get("last_activity_at")
            if last_active is not None and us != "pinned":
                days_since = (now - float(last_active)) / 86400
                if days_since > self.stale_after_days:
                    stale += 1

        archive_path = Path(self.archive_dir)
        archived_on_disk = (
            len([p for p in archive_path.iterdir() if p.is_dir()])
            if archive_path.is_dir() else 0
        )

        return {
            "enabled": self.enabled,
            "total_skills": total,
            "active": active,
            "archived": archived,
            "pinned": pinned,
            "stale": stale,
            "archived_on_disk": archived_on_disk,
            "stale_after_days": self.stale_after_days,
            "archive_after_days": self.archive_after_days,
            "last_run": self._last_run,
            "config": {
                "stale_after_days": self.stale_after_days,
                "archive_after_days": self.archive_after_days,
                "enabled": self.enabled,
            },
        }

    def _last_activity(self, name: str) -> None:
        usage = self._get_usage(name)
        usage["last_activity_at"] = time.time()
        self._set_usage(name, usage)
