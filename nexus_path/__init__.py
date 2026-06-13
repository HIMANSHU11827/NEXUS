"""
NEXUS PATH RESOLVER
Auto-adds the project root to sys.path so all module imports work
in both IDE analysis and runtime, regardless of working directory.
Import this at the top of any NEXUS entry-point file.
"""
import sys
import os

# Add project root to path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
