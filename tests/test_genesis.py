import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from typing import Any

import os
import shutil
from core.kernel import NexusKernel  # type: ignore
from core.tool_adapters import RegistryFileTools as NexusFileTools  # type: ignore


class TestNexusGenesis(unittest.TestCase):
    """
    NEXUS GENESIS INTEGRATION TEST
    The first 'A to Z' test to prove the Kernel,
    Tools, and Workspace are 100% operational.
    """

    test_ws: str = ""
    kernel: Any = None
    tools: Any = None

    @classmethod
    def setUpClass(cls):
        cls.test_ws = "./test_workspace"
        cls.kernel = NexusKernel(cls.test_ws)
        cls.tools = NexusFileTools(cls.test_ws)

    def test_boot_and_write(self):
        """Proves the Kernel can boot and the tools can write to disk."""
        print("[*] Testing Kernel Boot...")
        self.assertTrue(self.kernel.boot())

        print("[*] Testing Workspace File-Writing...")
        result = self.tools.write_file("genesis.txt", "A to Z Integration Matrix.")
        self.assertIn("Success", result)

        content = self.tools.read_file("genesis.txt")
        self.assertEqual(content, "A to Z Integration Matrix.")
        print("[PASS] Genesis Integration Verified.")


if __name__ == "__main__":
    unittest.main()
