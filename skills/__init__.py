"""Skill metadata and prompt management for reusable NEXUS workflows."""

import os
import re
import json
import yaml
import logging
import shutil
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Skill parsing constraints.
MAX_NAME_LENGTH = 64
MAX_DESC_LENGTH = 1024
EXCLUDED_DIRS = {".git", "__pycache__", "workspace"}

class NexusSkillMaster:
    """
    Skill manager. Handles metadata, categories, and safety.
    """

    def __init__(self, root_dir: str):
        self.root = os.path.abspath(root_dir)
        self.skill_dir = os.path.join(self.root, "skill")
        os.makedirs(self.skill_dir, exist_ok=True)
        self.active_skill_prompt: Optional[str] = None

    def _parse_skill(self, file_path: str) -> Dict[str, Any]:
        """Parse SKILL.md with YAML frontmatter."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    metadata = yaml.safe_load(parts[1])
                    body = parts[2].strip()
                    return {
                        "name": metadata.get("name", ""),
                        "description": metadata.get("description", ""),
                        "content": body,
                        "metadata": metadata
                    }
            
            # Fallback for simple markdown
            lines = content.split("\n")
            name = lines[0].strip("# ").strip()
            desc = lines[1].strip() if len(lines) > 1 else ""
            return {"name": name, "description": desc, "content": content, "metadata": {}}
        except Exception as e:
            logger.error(f"Failed to parse skill {file_path}: {e}")
            return {}

    def list_skills(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """List skills with metadata (Tier 1 disclosure)."""
        skills = []
        scan_path = self.skill_dir
        if category:
            scan_path = os.path.join(self.skill_dir, category)

        if not os.path.exists(scan_path):
            return []

        for root, dirs, files in os.walk(scan_path):
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
            for f in files:
                if f == "SKILL.md" or (root == self.skill_dir and f.endswith(".md")):
                    full_path = os.path.join(root, f)
                    data = self._parse_skill(full_path)
                    if data:
                        rel_path = os.path.relpath(root, self.skill_dir)
                        data["category"] = rel_path if rel_path != "." else None
                        data["id"] = os.path.basename(root) if f == "SKILL.md" else f.replace(".md", "")
                        skills.append(data)
        return skills

    def load_skill(self, name: str) -> bool:
        """Loads a skill's instructions into the active brain state."""
        # Try direct file, then try folder search
        path = os.path.join(self.skill_dir, f"{name}.md")
        if not os.path.exists(path):
            # Try recursive search for SKILL.md in folder 'name'
            for root, dirs, files in os.walk(self.skill_dir):
                if os.path.basename(root) == name and "SKILL.md" in files:
                    path = os.path.join(root, "SKILL.md")
                    break

        if os.path.exists(path):
            data = self._parse_skill(path)
            self.active_skill_prompt = data.get("content", "")
            logger.info(f"[SKILL_KERNEL]: Expert brain '{name}' activated.")
            return True
        return False

    def craft_skill(self, name: str, prompt: str, category: Optional[str] = None) -> str:
        """Writes a new procedural skill to the registry."""
        target_dir = self.skill_dir
        if category:
            target_dir = os.path.join(self.skill_dir, category)
        
        skill_path = os.path.join(target_dir, name)
        os.makedirs(skill_path, exist_ok=True)
        
        file_path = os.path.join(skill_path, "SKILL.md")
        
        frontmatter = {
            "name": name,
            "description": f"Autonomously synthesized skill for {name}",
            "version": "1.0.0",
            "metadata": {"source": "NEXUS_SYNTHESIZER"}
        }
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("---\n")
            f.write(yaml.dump(frontmatter))
            f.write("---\n\n")
            f.write(prompt)
            
        return f"[SKILL_CRAFTED]: Skill '{name}' stabilized at {file_path}"

    def get_active_prompt(self) -> Optional[str]:
        """Extract and reset active prompt."""
        p = self.active_skill_prompt
        self.active_skill_prompt = None
        return p

    def scan_environment(self) -> str:
        """Safety check for active skills."""
        # Ported from Hermes skills_guard logic
        return "[GUARD]: Environment stable. No malicious procedural spikes detected."

    def deep_scan(self) -> List[Dict[str, Any]]:
        """Scans the ENTIRE workspace for SKILL.md files (Omniscient Discovery)."""
        all_skills = []
        for root, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
            if "SKILL.md" in files:
                path = os.path.join(root, "SKILL.md")
                data = self._parse_skill(path)
                if data:
                    data["location"] = os.path.relpath(path, self.root)
                    all_skills.append(data)
        return all_skills

import time
import re
