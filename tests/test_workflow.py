import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

# Add project root and core to sys.path to resolve imports (including core.nexus_path)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
CORE_PATH = os.path.join(ROOT, "core")
if CORE_PATH not in sys.path:
    sys.path.insert(0, CORE_PATH)

from orchestrators.workflow_engine import NexusWorkflow


class TestWorkflowEngine(unittest.TestCase):
    def test_run_workflow_sequential_and_parallel(self):
        wf = NexusWorkflow()
        
        # Mock the LangChain chain stream to avoid network/local API requirements
        mock_chain = MagicMock()
        mock_chain.stream.return_value = ["mocked llm output"]
        wf.chain = mock_chain
        
        # Mock the terminal and files tools
        wf.terminal = MagicMock()
        wf.terminal.execute.return_value = "mocked bash output"
        
        wf.files = MagicMock()
        wf.files.write_file.return_value = "mocked file output"

        # Define steps with sequential and parallel types
        steps = [
            {"type": "prompt", "label": "step_seq_1", "payload": "hello"},
            {
                "type": "parallel",
                "label": "step_par",
                "steps": [
                    {"type": "prompt", "label": "sub_p", "payload": "sub prompt"},
                    {"type": "bash", "label": "sub_b", "payload": "sub bash"},
                    {"type": "write_file", "label": "sub_w", "filename": "test.txt", "content": "sub content"},
                ]
            },
            {"type": "bash", "label": "step_seq_2", "payload": "echo done"}
        ]
        
        results = wf.run_workflow(steps)
        
        # Verify sequential step results
        self.assertEqual(results.get("step_seq_1"), "mocked llm output")
        self.assertEqual(results.get("step_seq_2"), "mocked bash output")
        
        # Verify parallel sub-step results
        self.assertEqual(results.get("sub_p"), "mocked llm output")
        self.assertEqual(results.get("sub_b"), "mocked bash output")
        self.assertEqual(results.get("sub_w"), "mocked file output")


if __name__ == "__main__":
    unittest.main()
