"""Standard Operating Procedures for evolution tasks."""
import os
from typing import Optional
_SOP_DIR = os.path.dirname(os.path.abspath(__file__))

def load_sop(name: str) -> Optional[str]:
    path = os.path.join(_SOP_DIR, f"{name}.md")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return None

def list_sops() -> list:
    sops = []
    for f in os.listdir(_SOP_DIR):
        if f.endswith(".md"):
            sops.append(f[:-3])
    return sorted(sops)
