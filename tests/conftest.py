"""Shared fixtures for NEXUS evolution tests."""
import subprocess
import sys
from pathlib import Path

import pytest

# Check if sentence_transformers works (can cause C stack overflow on Python 3.14)
_nate_available = True
try:
    result = subprocess.run(
        [sys.executable, "-c", "import sentence_transformers; print('ok')"],
        capture_output=True, text=True, timeout=15,
    )
    _nate_available = result.returncode == 0 and result.stdout.strip() == "ok"
except Exception:
    _nate_available = False

if not _nate_available:
    _nate_dir = Path(__file__).resolve().parent / "test_nate"
    if _nate_dir.is_dir():
        import warnings
        warnings.warn("sentence_transformers unavailable — skipping NATE tests")

# Ensure script subdirectories are discoverable by pytest
_tests_dir = Path(__file__).resolve().parent
for subdir in _tests_dir.rglob("scripts"):
    if subdir.is_dir() and str(subdir) not in sys.path:
        sys.path.insert(0, str(subdir))


if not _nate_available:
    def pytest_collection_modifyitems(config, items):
        _nate_dir = Path(__file__).resolve().parent / "test_nate"
        skip_nate = pytest.mark.skip(reason="sentence_transformers unavailable (C stack overflow on Python 3.14)")
        for item in items:
            if str(item.fspath).startswith(str(_nate_dir)):
                item.add_marker(skip_nate)


@pytest.fixture
def root():
    return Path(".").resolve()


@pytest.fixture
def sample_tool_def():
    return {
        "name": "test_tool",
        "description": "A test tool for evolution testing",
        "params": {"arg1": {"type": "string", "description": "First argument"}},
    }


@pytest.fixture
def sample_skill_name():
    return "test_skill"


@pytest.fixture
def sample_plugin_name():
    return "test_plugin"


@pytest.fixture
def sample_memory_entry():
    return {
        "id": 1,
        "role": "user",
        "content": "This is a sample memory for testing",
    }


@pytest.fixture
def sample_knowledge_title():
    return "Test Knowledge Entry"
