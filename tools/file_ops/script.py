import os
import re
import glob
from typing import List, Dict, Any, Optional


class NexusFileTools:
    """
    Advanced file orchestration system supporting atomic edits, 
    project-wide search, and persistent workspace management.
    """

    def __init__(self, root_dir: str = "./workspace"):
        self.root = os.path.abspath(root_dir)
        if not os.name == 'nt' or not self.root.startswith('\\\\'): # Basic safety
            if not os.path.exists(self.root):
                os.makedirs(self.root)
        
        self.backup_dir = os.path.join(self.root, ".nexus", "backups")
        os.makedirs(self.backup_dir, exist_ok=True)

    def _backup(self, filename: str, content: str):
        """Creates a timestamped backup of the file content."""
        import time
        timestamp = int(time.time())
        safe_name = filename.replace("/", "_").replace("\\", "_")
        backup_path = os.path.join(self.backup_dir, f"{safe_name}.{timestamp}.bak")
        with open(backup_path, "w", encoding="utf-8") as f:
            f.write(content)

    def write_file(self, filename: str, content: str) -> str:
        """Writes a new file or overwrites an existing one."""
        try:
            path = os.path.join(self.root, filename)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Success: {filename} written to workspace."
        except Exception as e:
            return f"Error: {str(e)}"

    def edit_file(
        self, filename: str, old_string: str, new_string: str, replace_all: bool = False
    ) -> str:
        """
        Atomic Search-and-Replace with Quote Normalization.
        Ensures content consistency and allows precise edits.
        """
        try:
            path = os.path.join(self.root, filename)
            if not os.path.exists(path):
                return f"[FILE_NOT_FOUND]: {filename}"

            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            # Create backup
            self._backup(filename, content)

            # --- [SMART_MATCHING_PROTOCOL] ---
            # 1. Exact Match (Highest Priority)
            if old_string in content:
                count = content.count(old_string)
                if count > 1 and not replace_all:
                    return f"[EDIT_ERROR]: Found {count} occurrences. Use 'replace_all=True' or be more specific."
                new_content = content.replace(
                    old_string, new_string, -1 if replace_all else 1
                )
            else:
                # 2. Whitespace-Insensitive Match (Handling Indentation Mismatches)
                lines = content.splitlines()
                old_lines = old_string.splitlines()
                
                if not old_lines: return "[EDIT_ERROR]: Empty search string."
                
                # Try to find a block of lines that match when stripped
                found_start = -1
                for i in range(len(lines) - len(old_lines) + 1):
                    match = True
                    for j in range(len(old_lines)):
                        if lines[i+j].strip() != old_lines[j].strip():
                            match = False
                            break
                    if match:
                        found_start = i
                        break
                
                if found_start != -1:
                    # We found a fuzzy match! Reconstruct with original indentation if possible
                    # or just replace the block.
                    new_lines = lines[:found_start] + new_string.splitlines() + lines[found_start + len(old_lines):]
                    new_content = "\n".join(new_lines)
                else:
                    return f"[EDIT_ERROR]: String not found (even with fuzzy matching). Please provide exact content."

            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
            return f"🎉 Successfully updated {filename} (Backup created)."

        except Exception as e:
            return f"[FILE_ERROR]: {str(e)}"

    def read_file(self, filename: str) -> str:
        """Reads a file with project-level path resolution."""
        try:
            project_root = os.path.dirname(self.root)
            target_path = os.path.abspath(os.path.join(self.root, filename))

            if not target_path.startswith(project_root):
                return "[ACCESS_DENIED]: Path is outside the NEXUS project tree."

            if not os.path.exists(target_path):
                return f"[FILE_NOT_FOUND]: {filename}"

            with open(target_path, "r", encoding="utf-8") as f:
                content = f.read()
                return content[:8000] + (
                    "\n...[TRUNCATED]" if len(content) > 8000 else ""
                )
        except Exception as e:
            return f"[FILE_ERROR]: {str(e)}"

    def list_files(self, directory: str = ".", recursive: bool = True) -> str:
        """Lists files with exclusion of common binary/vendor directories."""
        try:
            exclude = {".git", "__pycache__", "node_modules", "venv", ".env"}
            files = []
            scan_path = os.path.join(self.root, directory)

            for root, dirs, filenames in os.walk(scan_path):
                dirs[:] = [d for d in dirs if d not in exclude]
                for f in filenames:
                    rel = os.path.relpath(os.path.join(root, f), self.root)
                    files.append(rel)
                    if len(files) > 100:
                        break
                if not recursive:
                    break

            return "\n".join(files) if files else "[EMPTY_DIRECTORY]"
        except Exception as e:
            return f"[LIST_ERROR]: {str(e)}"

    def search_files(self, pattern: str, directory: str = ".") -> str:
        """Searches file content for a regex pattern (grep-style)."""
        try:
            results = []
            scan_path = os.path.join(self.root, directory)
            regex = re.compile(pattern, re.IGNORECASE)

            for root, _, filenames in os.walk(scan_path):
                for f in filenames:
                    path = os.path.join(root, f)
                    try:
                        with open(
                            path, "r", encoding="utf-8", errors="ignore"
                        ) as f_obj:
                            for i, line in enumerate(f_obj, 1):
                                if regex.search(line):
                                    rel = os.path.relpath(path, self.root)
                                    results.append(f"{rel}:{i}: {line.strip()}")
                                    if len(results) > 50:
                                        break
                    except (OSError, IOError):
                        continue
                    if len(results) > 50:
                        break

            return "\n".join(results) if results else "[NO_MATCHES]"
        except Exception as e:
            return f"[SEARCH_ERROR]: {str(e)}"

    def craft_skill(self, name: str, doc: str) -> str:
        """Create a new 'clade:' skill dynamically."""
        try:
            project_root = os.path.dirname(self.root)
            skills_dir = os.path.join(project_root, "external_skills", "skills", name)
            os.makedirs(skills_dir, exist_ok=True)
            with open(os.path.join(skills_dir, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write(doc)
            return f"🎉 Skill '{name}' successfully crafted. You can now use 'clade:{name}'."
        except Exception as e:
            return f"[CRAFT_ERROR]: {str(e)}"


if __name__ == "__main__":
    t = NexusFileTools()
    print(t.list_files())
