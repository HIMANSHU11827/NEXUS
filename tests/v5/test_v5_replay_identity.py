import json
from types import SimpleNamespace

from nexus.main_agent.learning import V5Learning


def test_replay_entries_have_unique_ids_and_record_digests(tmp_path):
    learner = V5Learning()
    learner.root_dir = str(tmp_path)
    learner.session_id = "session-1"
    learner._current_turn_id = "turn-1"
    perceived = SimpleNamespace(original_input="inspect")
    result = {"success": True, "response": "done", "actions": []}
    turn = SimpleNamespace(turn_id="turn-1")
    learner._log_turn_replay(perceived, result, turn)
    learner._log_turn_replay(perceived, result, turn)
    lines = (tmp_path / ".nexus" / "v5" / "replays.jsonl").read_text(encoding="utf-8").splitlines()
    entries = [json.loads(line) for line in lines]
    assert len(entries) == 2
    assert entries[0]["entry_id"] != entries[1]["entry_id"]
    assert len(entries[0]["record_sha256"]) == 64
    assert len(entries[1]["record_sha256"]) == 64
