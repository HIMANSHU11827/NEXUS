"""
NEXUS OUTPUT OPTIMIZER — Token-efficient tool output compression.
Reduces token waste by intelligently truncating, summarizing, and compressing tool outputs.
Every token saved = money saved + faster responses.
"""

import re
import hashlib
from typing import Optional, List, Dict, Any


class OutputOptimizer:
    """
    Compresses tool outputs to use minimum tokens while preserving maximum information.
    """

    # Max chars per tool type (tight limits = less token waste)
    LIMITS = {
        "bash": 2000,
        "file_read": 3000,
        "file_edit": 500,
        "glob": 1000,
        "grep": 1500,
        "web_search": 800,
        "web_fetch": 2000,
        "rag": 1500,
        "lsp": 500,
        "test": 1000,
        "git": 500,
        "default": 1500,
    }

    @classmethod
    def compress(
        cls, output: str, tool_name: str = "default", max_chars: int = None
    ) -> str:
        """Compress tool output to minimum tokens while keeping useful info."""
        if not output:
            return ""

        limit = max_chars or cls.LIMITS.get(tool_name, cls.LIMITS["default"])

        # Already short enough
        if len(output) <= limit:
            return output

        if tool_name == "bash":
            return cls._compress_bash(output, limit)
        elif tool_name == "file_read":
            return cls._compress_file(output, limit)
        elif tool_name == "glob":
            return cls._compress_list(output, limit)
        elif tool_name == "grep":
            return cls._compress_grep(output, limit)
        elif tool_name == "web_search":
            return cls._compress_search(output, limit)
        elif tool_name in ("test", "git"):
            return cls._compress_log(output, limit)
        else:
            return cls._compress_generic(output, limit)

    @classmethod
    def _compress_bash(cls, output: str, limit: int) -> str:
        """Smart bash output compression."""
        lines = output.strip().split("\n")

        # If file listing, collapse to compact format
        if all("/" in l or "\\" in l or "." in l for l in lines[:5] if l.strip()):
            # It's a file listing - show count + first/last
            total = len(lines)
            head = lines[:10]
            tail = lines[-5:] if total > 15 else []
            result = "\n".join(head)
            if tail:
                result += f"\n... [{total - 15} more lines] ...\n"
                result += "\n".join(tail)
            return result[:limit]

        # Default: head + tail
        if len(lines) > 20:
            head = lines[:12]
            tail = lines[-5:]
            collapsed = (
                "\n".join(head)
                + f"\n... [{len(lines) - 17} lines omitted] ...\n"
                + "\n".join(tail)
            )
            return collapsed[:limit]

        return output[:limit]

    @classmethod
    def _compress_file(cls, output: str, limit: int) -> str:
        """File content compression - keep structure, trim middle."""
        if len(output) <= limit:
            return output

        # Keep first portion + last few lines (context preservation)
        head_chars = int(limit * 0.7)
        tail_chars = int(limit * 0.2)

        head = output[:head_chars]
        tail = output[-tail_chars:] if len(output) > tail_chars else ""
        omitted = len(output) - head_chars - tail_chars

        result = head
        if tail:
            result += f"\n\n... [{omitted} chars omitted] ...\n\n" + tail
        return result

    @classmethod
    def _compress_list(cls, output: str, limit: int) -> str:
        """List output compression - count + sample."""
        lines = [l for l in output.split("\n") if l.strip()]
        if len(lines) <= 20:
            return output[:limit]

        sample = lines[:15]
        total = len(lines)
        # Extract file extensions for summary
        exts = {}
        for l in lines:
            if "." in l:
                ext = l.rsplit(".", 1)[-1].lower()[:5]
                exts[ext] = exts.get(ext, 0) + 1

        ext_summary = ", ".join(
            f".{k}({v})" for k, v in sorted(exts.items(), key=lambda x: -x[1])[:8]
        )
        return "\n".join(sample) + f"\n\n[{total} total files] Types: {ext_summary}"

    @classmethod
    def _compress_grep(cls, output: str, limit: int) -> str:
        """Grep output compression - group by file."""
        lines = output.split("\n")
        if len(lines) <= 10:
            return output[:limit]

        # Group matches by file
        files = {}
        for line in lines:
            if ":" in line:
                fname = line.split(":", 1)[0]
                if fname not in files:
                    files[fname] = []
                files[fname].append(line)

        result = []
        for fname, matches in list(files.items())[:10]:
            result.append(f"{fname}: {len(matches)} matches")
            for m in matches[:3]:
                result.append(f"  {m.split(':', 1)[-1].strip()[:100]}")
            if len(matches) > 3:
                result.append(f"  ... +{len(matches) - 3} more")

        return "\n".join(result)[:limit]

    @classmethod
    def _compress_search(cls, output: str, limit: int) -> str:
        """Search result compression."""
        # Remove duplicate whitespace
        compressed = re.sub(r"\n{3,}", "\n\n", output)
        compressed = re.sub(r" {2,}", " ", compressed)
        return compressed[:limit]

    @classmethod
    def _compress_log(cls, output: str, limit: int) -> str:
        """Log/test output compression - keep pass/fail, trim details."""
        lines = output.split("\n")

        # Keep summary lines (PASS, FAIL, ERROR)
        important = [
            l
            for l in lines
            if any(
                kw in l.upper()
                for kw in [
                    "PASS",
                    "FAIL",
                    "ERROR",
                    "OK",
                    "WARN",
                    "SKIP",
                    "TOTAL",
                    "SUMMARY",
                ]
            )
        ]

        if important:
            return "\n".join(important)[:limit]
        return output[:limit]

    @classmethod
    def _compress_generic(cls, output: str, limit: int) -> str:
        """Generic compression - head + tail with middle omitted."""
        if len(output) <= limit:
            return output
        head = output[: int(limit * 0.7)]
        tail = output[-int(limit * 0.2) :]
        return head + f"\n... [{len(output) - limit} chars] ...\n" + tail

    @classmethod
    def hash_output(cls, output: str) -> str:
        """Hash output for caching/dedup."""
        return hashlib.md5(output.encode()).hexdigest()[:8]


class ToolCache:
    """Simple tool result cache to avoid duplicate calls."""

    _cache: Dict[str, Any] = {}
    _max_size = 100

    @classmethod
    def get_key(cls, tool_name: str, params: Dict[str, Any]) -> str:
        """Generate cache key from tool name + params."""
        param_str = str(sorted(params.items()))
        return hashlib.md5(f"{tool_name}:{param_str}".encode()).hexdigest()[:12]

    @classmethod
    def get(cls, tool_name: str, params: Dict[str, Any]) -> Optional[str]:
        """Get cached result if available."""
        key = cls.get_key(tool_name, params)
        return cls._cache.get(key)

    @classmethod
    def set(cls, tool_name: str, params: Dict[str, Any], result: str):
        """Cache a tool result."""
        if len(cls._cache) >= cls._max_size:
            # Remove oldest half
            keys = list(cls._cache.keys())
            for k in keys[: cls._max_size // 2]:
                del cls._cache[k]
        key = cls.get_key(tool_name, params)
        cls._cache[key] = result

    @classmethod
    def clear(cls):
        cls._cache.clear()

    @classmethod
    def stats(cls) -> Dict[str, int]:
        return {"entries": len(cls._cache), "max": cls._max_size}
