import subprocess
import os
import re
from typing import List, Dict, Any

class NexusTestTool:
    """
    Autonomous verification engine with failure analysis, 
    synthetic fault detection, and test-result parsing.
    """

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)

    def run_tests(self, target: str = "tests/") -> str:
        """Runs pytest on the target directory and parses results."""
        target_path = os.path.join(self.root, target)
        if not os.path.exists(target_path):
            return f"[ERROR]: Test path {target} not found."

        try:
            # Use -v for verbose to get failure details
            # Use --tb=short to keep output manageable for LLM
            process = subprocess.run(
                ["pytest", "-v", "--tb=short", target_path],
                capture_output=True,
                text=True,
                timeout=120
            )
            
            output = process.stdout + "\n" + process.stderr
            return self._parse_output(output, process.returncode)
        except Exception as e:
            return f"❌ TEST_EXECUTION_ERROR: {str(e)}"

    def _parse_output(self, output: str, exit_code: int) -> str:
        """Parses pytest output into a high-density summary for the LLM."""
        if exit_code == 0:
            count = re.search(r"(\d+) passed", output)
            return f"✅ ALL TESTS PASSED. Details: {count.group(1) if count else 'N/A'} tests verified."

        # Extract failures
        failures = []
        # Look for FAILED or ERROR blocks
        matches = re.finditer(r"____ (.*?) ____\n(.*?)\n\n", output, re.DOTALL)
        for m in matches:
            failures.append(f"FAIL: {m.group(1).split('/')[-1]}\nREASON: {m.group(2).strip()}")

        # Summarize pass/fail counts
        summary = re.search(r"(=+ (.*?) =+)", output)
        summary_text = summary.group(2) if summary else "Unknown summary."

        header = "❌ TEST_FAILURES_DETECTED\n"
        body = "\n\n".join(failures[:5]) # Cap at 5 failures for context safety
        footer = f"\n\nOverall: {summary_text}"
        
        return header + body + footer

if __name__ == "__main__":
    tester = NexusTestTool()
    # print(tester.run_tests("tests/"))
