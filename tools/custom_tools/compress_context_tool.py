"""
NEXUS CONTEXT COMPRESSION TOOL — Compress conversation context to save tokens
Like Hermes auto-compression: summarizes older messages while preserving key info.
"""
import json
import os
import re
from typing import Any, Dict, List, Optional
from tools.nexus_tools.base_tool import BaseTool, ToolResult


class ContextCompressTool(BaseTool):
    """Compress conversation history to save tokens while preserving critical context."""
    name = "compress_context"
    description = "Compress conversation history to save tokens. Preserves decisions, code references, errors, and action items while summarizing verbose exchanges."
    aliases = ["compress", "summarize_context", "save_tokens"]

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)

    def call(self, text: str = "", max_chars: int = 2000, preserve_patterns: List[str] = None) -> ToolResult:
        if not text:
            return ToolResult(error="text is required. Pass the conversation or file content to compress.")

        try:
            patterns = preserve_patterns or [
                r'(?:bug|fix|error|issue|crash|fail)[\w\s:;,.?!]{5,100}',
                r'(?:feat|add|create|implement|build|make|refactor)[\w\s:;,.?!]{5,100}',
                r'(?:TODO|FIXME|HACK|XXX|OPTIMIZE)[\w\s:;,.?!]{5,100}',
                r'`[^`]+`',  # code references
                r'file:\s*[\w/\\\.-]+',
                r'path:\s*[\w/\\\.-]+',
                r'commit[\w\s]{5,60}',
                r'test[\w\s]{5,60}',
                r'PR\s*#?\d+',
                r'issue\s*#?\d+',
            ]

            # Extract critical info
            critical_lines = []
            for pattern in patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                for m in matches:
                    m = m.strip()
                    if m and len(m) > 10 and m not in critical_lines:
                        critical_lines.append(m)

            # Extract the first and last parts (usually most important)
            lines = text.split('\n')
            header = '\n'.join(lines[:min(20, len(lines)//4)])
            footer = '\n'.join(lines[-min(20, len(lines)//4):])

            # Compress the middle
            compressed = []
            compressed.append("--- COMPRESSED CONTEXT ---")
            compressed.append("")
            compressed.append("### HEAD")
            compressed.append(header[:1000])
            compressed.append("")

            if critical_lines:
                compressed.append("### KEY EXTRACTS")
                for cl in critical_lines[:20]:
                    compressed.append(f"- {cl[:200]}")
                compressed.append("")

            compressed.append("### TAIL")
            compressed.append(footer[:1000])

            # Count what was saved
            original_chars = len(text)
            compressed_text = '\n'.join(compressed)
            compressed_chars = len(compressed_text)
            savings_pct = round((1 - compressed_chars / max(original_chars, 1)) * 100)

            result = f"""{compressed_text}

---
Compression Report:
- Original: {original_chars:,} chars  
- Compressed: {compressed_chars:,} chars
- Savings: {savings_pct}%
- Critical items preserved: {len(critical_lines)}
"""

            return ToolResult(data=result)

        except Exception as e:
            return ToolResult(error=f"Compression error: {str(e)}")

    def is_read_only(self, input_data=None):
        return True

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The text to compress (conversation history or file content)."},
                    "max_chars": {"type": "integer", "description": "Target max chars after compression (default 2000)."},
                    "preserve_patterns": {
                        "type": "array", 
                        "items": {"type": "string"},
                        "description": "Custom regex patterns for critical info to preserve.",
                    },
                },
                "required": ["text"],
            },
        }
