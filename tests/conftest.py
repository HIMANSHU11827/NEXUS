"""Shared fixtures for NEXUS evolution tests."""
import sys
from pathlib import Path
import pytest

# Ensure script subdirectories are discoverable by pytest
_tests_dir = Path(__file__).resolve().parent
for subdir in _tests_dir.rglob("scripts"):
    if subdir.is_dir() and str(subdir) not in sys.path:
        sys.path.insert(0, str(subdir))


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
