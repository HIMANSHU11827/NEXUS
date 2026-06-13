import os
import hashlib
import json
import time
from typing import Dict, List, Any, Optional

class NexusSemanticIndexer:
    """
    NEXUS SEMANTIC INDEXER 1.0
    Builds a high-fidelity map of the repository to ensure NEXUS always has perfect grounding.
    """
    def __init__(self, root_dir: str):
        self.root = root_dir
        self.index_path = os.path.join(self.root, "workspace", "semantic_index.json")
        self.index: Dict[str, Any] = {}
        self.load()

    def load(self):
        if os.path.exists(self.index_path):
            try:
                with open(self.index_path, "r") as f:
                    self.index = json.load(f)
            except Exception: self.index = {}

    def save(self):
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        with open(self.index_path, "w") as f:
            json.dump(self.index, f, indent=2)

    def _get_hash(self, path: str) -> str:
        try:
            with open(path, "rb") as f:
                return hashlib.md5(f.read()).hexdigest()
        except Exception: return ""

    def scan(self):
        """Scans the repository and updates the index with structural and semantic hints."""
        start = time.time()
        count = 0
        exclude_dirs = {".git", "__pycache__", "node_modules", "workspace", "models", "data", "logs", ".antigravity"}
        
        for root, dirs, files in os.walk(self.root):
            # Efficiently prune directories
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            
            for f in files:
                if f.endswith((".py", ".md", ".json", ".yaml", ".txt", ".js", ".ts", ".tsx")):
                    full_path = os.path.join(root, f)
                    rel_path = os.path.relpath(full_path, self.root).replace("\\", "/")
                    f_hash = self._get_hash(full_path)
                    
                    if rel_path not in self.index or self.index[rel_path]["hash"] != f_hash:
                        try:
                            with open(full_path, "r", encoding="utf-8", errors="ignore") as f_obj:
                                content = f_obj.read(2000) # Read first 2KB for hints
                                # Extract keywords (simple heuristic)
                                keywords = list(set(re.findall(r"\b[a-zA-Z_]{5,}\b", content)))[:20]
                                
                            self.index[rel_path] = {
                                "hash": f_hash,
                                "last_scanned": time.time(),
                                "size": os.path.getsize(full_path),
                                "keywords": keywords,
                                "type": "code" if f.endswith((".py", ".js", ".ts")) else "doc"
                            }
                            count += 1
                        except Exception: continue
                        
        self.save()
        return count, time.time() - start

    def get_grounding_map(self, query: Optional[str] = None) -> str:
        """Returns a relevant summarized map of the repository for prompt injection."""
        summary = ["### [NEXUS REPOSITORY GROUNDING MAP]"]
        
        # If query is provided, prioritize files with matching keywords
        sorted_files = list(self.index.items())
        if query:
            q_words = set(query.lower().split())
            sorted_files.sort(key=lambda x: len(set([k.lower() for k in x[1].get("keywords", [])]) & q_words), reverse=True)

        for path, info in sorted_files[:50]: # Cap at 50 most relevant files
            k_str = ", ".join(info.get("keywords", [])[:5])
            summary.append(f"- {path} ({info['type']}) | Key: {k_str}")
            
        return "\n".join(summary)

    def get_context_map(self) -> str:
        """Alias for get_grounding_map for system compatibility."""
        return self.get_grounding_map()

import re # Ensure re is available for keywords
