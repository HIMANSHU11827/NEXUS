"""Optional llama.cpp compiler boundary."""

from __future__ import annotations


def compile_llama_cpp() -> dict:
    """Report unsupported compilation explicitly.

    Nexus currently has no portable build contract for llama.cpp.  Returning a
    structured unavailable result prevents the API from presenting a skipped
    operation as a successful compilation.
    """
    return {
        "status": "unavailable",
        "engine": "llama.cpp",
        "reason": "native llama.cpp compilation is not configured",
    }
