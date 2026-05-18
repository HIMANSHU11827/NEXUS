import os
import ast
from typing import List, Dict, Any, Optional

class AtlasCognitiveMapper:
    """
    NEXUS ATLAS — COGNITIVE LOGIC MAPPER
    Summarizes the logical footprint of a directory without reading every file content individually.
    """

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)

    def map_directory(self, target_dir: str) -> str:
        """Generates a structural 'Atlas Map' of a directory's internal logic."""
        abs_target = os.path.join(self.root, target_dir) if not os.path.isabs(target_dir) else target_dir
        if not os.path.isdir(abs_target):
            return f"Error: {target_dir} is not a valid directory."

        logic_map = []
        for root, _, files in os.walk(abs_target):
            # Skip hidden or heavy dirs
            if any(x in root for x in [".git", "__pycache__", "node_modules", "knowledge"]):
                continue
                
            for f in files:
                if f.endswith(".py"):
                    path = os.path.join(root, f)
                    rel_p = os.path.relpath(path, self.root).replace("\\", "/")
                    
                    try:
                        with open(path, "r", encoding="utf-8") as f_obj:
                            source = f_obj.read()
                            tree = ast.parse(source)
                            
                        file_logic = []
                        for node in ast.walk(tree):
                            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                # Extract first line of docstring for 'Purpose' if possible
                                doc = ast.get_docstring(node)
                                purpose = doc.split("\n")[0] if doc else "Undocumented logic"
                                type_prefix = "async function" if isinstance(node, ast.AsyncFunctionDef) else "function"
                                file_logic.append(f"  - {type_prefix} {node.name}(): {purpose}")
                            elif isinstance(node, ast.ClassDef):
                                bases = [ast.dump(base) for base in node.bases]
                                file_logic.append(f"  - class {node.name}({', '.join(bases)}): [Structure definition]")
                        
                        if file_logic:
                            logic_map.append(f"### [File: {rel_p}]\n" + "\n".join(file_logic))
                    except Exception as e:
                        # logic_map.append(f"### [File: {rel_p}] - Parse Error: {e}")
                        continue

        header = f"# NEXUS ATLAS LOGIC MAP — {target_dir}\n"
        if not logic_map:
            return header + "No logical symbols found in this directory."
            
        return header + "\n\n".join(logic_map)

if __name__ == "__main__":
    import sys
    root = "." if len(sys.argv) < 2 else sys.argv[1]
    mapper = AtlasCognitiveMapper(root)
    # print(mapper.map_directory("orchestrators"))
