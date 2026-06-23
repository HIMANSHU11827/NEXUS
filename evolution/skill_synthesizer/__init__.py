"""Skill Synthesizer — auto-generates new skills from examples."""

from __future__ import annotations
import os
from pathlib import Path
from typing import Any, Dict, Optional, List


class SkillSynthesizer:
    """Synthesizes new skills from natural language descriptions."""

    def __init__(self, root: str):
        self.root = root
        self._skills_dir = Path(root) / "skills"
        self._skills_dir.mkdir(parents=True, exist_ok=True)

    def synthesize(self, name: str, description: str, examples: Optional[List[str]] = None) -> Dict[str, Any]:
        safe_name = name.lower().replace(" ", "_")
        prompt_lines = [f"# {name}", "", description, ""]
        if examples:
            prompt_lines.append("## Examples")
            for ex in examples:
                prompt_lines.append(f"- {ex}")
        content = "\n".join(prompt_lines)
        fpath = self._skills_dir / f"{safe_name}.md"
        meta = f"---\nid: {safe_name}\nname: {name}\ndescription: {description}\ncategory: synthesized\n---\n"
        fpath.write_text(meta + content, encoding="utf-8")
        return {"id": safe_name, "name": name, "filepath": str(fpath), "synthesized": True}

    def list_synthesized(self) -> List[Dict[str, Any]]:
        results = []
        for f in self._skills_dir.glob("*.md"):
            results.append({"id": f.stem, "filepath": str(f)})
        return results
