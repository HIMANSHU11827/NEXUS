import json

from context.persistence import NexusFilePersistence
from gateways.session_bus_integration import GatewaySessionManager
from memory import MemoryManager
from utils import session_bus
from evolution.memory_forge.scripts.forge import MemoryForge


def test_context_persistence_normalizes_session_and_checkpoint_paths(tmp_path):
    persistence = NexusFilePersistence(str(tmp_path))

    path = persistence.checkpoint_session(
        "../../escape.json",
        [{"role": "user", "content": "safe"}],
        checkpoint_id="../../checkpoint/one",
    )

    assert str(tmp_path) in path
    assert "escape" in path
    assert path.endswith("escape.one.json")
    assert not (tmp_path.parent / "escape.json.checkpoint").exists()
    payload = json.loads(open(path, encoding="utf-8").read())
    assert payload["session_id"] == "escape"
    assert payload["checkpoint_id"] == "one"


def test_gateway_session_manager_normalizes_lookup_and_path_ids(tmp_path):
    manager = GatewaySessionManager(str(tmp_path))

    paths = manager.get_session_paths("../../gateway-escape.json")

    assert all(str(tmp_path) in path for path in paths.values())
    assert all(".." not in path for path in paths.values())
    assert paths["memory"].endswith("gateway-escape.json")


def test_memory_manager_normalizes_session_id(tmp_path):
    manager = MemoryManager(str(tmp_path), session_id="../../memory-escape.json")

    assert manager.session_id == "memory-escape"
    assert ".." not in manager.get_statistics().get("session_id", "")
    manager.shutdown()


def test_active_session_bus_isolated_per_project_root(tmp_path):
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"

    session_bus.set_active_session_id(str(first_root), "../../first.json")
    session_bus.set_active_session_id(str(second_root), "second")

    assert session_bus.get_active_session_id(str(first_root), "default") == "first"
    assert session_bus.get_active_session_id(str(second_root), "default") == "second"


def test_memory_forge_name_cannot_escape_memory_root(tmp_path):
    result = MemoryForge(str(tmp_path)).forge(
        "../../escape/memory", "verified evidence"
    )

    assert result["created"] is True
    assert str(tmp_path / "data" / "memory_forge") in result["path"]
    assert ".." not in result["path"]
