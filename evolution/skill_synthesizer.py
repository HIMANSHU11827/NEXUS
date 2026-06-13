import os
import json
import logging
import re
import time
import asyncio
from typing import List, Dict, Any, Optional
from providers.router import ModelRouter

logger = logging.getLogger(__name__)

class SkillSynthesizer:
    """
    The 'Hive Mind' of NEXUS. Watches for success and harvests workflows.
    """

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)
        self.skill_dir = os.path.join(self.root, "skill")
        os.makedirs(self.skill_dir, exist_ok=True)
        # Use a dedicated router for synthesis to allow custom settings
        self.router = ModelRouter()

    def synthesize_from_history(self, history: List[Dict[str, Any]], task_name: str) -> Optional[str]:
        """
        Analyze recent message history. If a complex multi-step success is found,
        synthesize a new SKILL.md.
        """
        if len(history) < 6:
            return None # Not complex enough

        logger.info(f"[SKILL_SYNTH]: Analyzing success trajectory for '{task_name}'...")

        # 1. Ask the Brain to extract a reusable procedure
        history_text = json.dumps(history[-15:], indent=2)
        
        prompt = f"""You are the NEXUS Evolution Kernel (Sovereign Tier). 
I am providing a successful conversation history for the task: "{task_name}".

YOUR GOAL:
Extract the EXACT repeatable procedure that led to success. 
Write a new "NEXUS SKILL" document with YAML frontmatter.

FORMAT:
---
name: [SKILL_ID_IN_SNAKE_CASE]
description: [Clear primary objective]
role: [Specialized Role Name]
version: 1.0.0
metadata:
  source: NEXUS_SYNTHESIZER
  original_task: "{task_name}"
---

# [SKILL_NAME] 🧠

## Procedural Protocol
1. **[Step 1]**: [Action]
2. **[Step 2]**: [Action]

## Verification
[How to check success]

HISTORY:
{history_text}

Respond ONLY with Markdown. If this task is similar to an existing skill, produce an UPGRADED version with incremented version number.
"""

        try:
            # 2. Use the router synchronously to avoid event loop conflicts in the main loop
            # We target a heavy model for high-precision extraction
            skill_content = self.router.generate(prompt=prompt, mode="heavy")
            
            if not skill_content or "---" not in skill_content:
                return None

            # Extract ID from YAML
            matches = re.search(r"name:\s*([\w_]+)", skill_content)
            skill_id = matches.group(1).lower() if matches else f"auto_{int(time.time())}"
            
            file_path = os.path.join(self.skill_dir, f"{skill_id}.md")
            
            # Handle version increment if file exists
            if os.path.exists(file_path):
                logger.info(f"[SKILL_SYNTH]: Skill '{skill_id}' already exists. Refinement applied.")

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(skill_content)
            
            logger.info(f"[SKILL_SYNTH]: Successfully codified procedural memory: {skill_id}.md")
            return f"EVOLUTION_COMPLETE: Skill '{skill_id}' synchronized to registry."
        except Exception as e:
            logger.error(f"Skill synthesis failed: {e}")
            return None
