import subprocess
import os
from typing import List, Dict, Any, Optional

class NexusGitTools:
    """
    NEXUS GIT CONNECTOR 1.0 (PRODUCTION-GRADE)
    Enables autonomous repository management and branch logic.
    """

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)

    def _run_git(self, args: List[str]) -> str:
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=self.root,
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode != 0:
                return f"[GIT_ERROR]: {result.stderr.strip()}"
            return result.stdout.strip()
        except Exception as e:
            return f"[SYSTEM_ERROR]: {str(e)}"

    def get_status(self) -> str:
        """Returns the current porcelain status of the repository."""
        return self._run_git(["status", "--porcelain"])

    def get_diff(self, filename: Optional[str] = None) -> str:
        """Returns the current diff, optionally for a specific file."""
        args = ["diff", "HEAD"]
        if filename:
            args.append(filename)
        return self._run_git(args)

    def get_branch(self) -> str:
        """Returns the current branch name."""
        return self._run_git(["rev-parse", "--abbrev-ref", "HEAD"])

    def commit(self, message: str) -> str:
        """Stages all changes and commits them."""
        # Stage everything
        self._run_git(["add", "."])
        # Commit
        return self._run_git(["commit", "-m", message])

    def get_last_commits(self, n: int = 5) -> str:
        """Returns the last N commit messages."""
        return self._run_git(["log", f"-n {n}", "--oneline"])

    def create_branch(self, name: str) -> str:
        """Creates and switches to a new branch."""
        return self._run_git(["checkout", "-b", name])

    def execute(self, cmd_string: str) -> str:
        """Universal entry point for the coordinator."""
        import shlex
        args = shlex.split(cmd_string)
        return self._run_git(args)

if __name__ == "__main__":
    g = NexusGitTools()
    print("Branch:", g.get_branch())
    print("Status:", g.get_status())
