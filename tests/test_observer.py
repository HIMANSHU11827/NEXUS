import io
import json

from nexus.observer import run_observer


def test_observer_replays_public_events_and_resumes_by_sequence(tmp_path):
    events_dir = tmp_path / "workspace" / "work_events"
    events_dir.mkdir(parents=True)
    path = events_dir / "demo.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"sequence": 1, "event_type": "run.started", "status": "running"}),
                json.dumps({"sequence": 2, "event_type": "tool.started", "status": "running", "visibility": "internal"}),
                json.dumps({"sequence": 3, "event_type": "run.completed", "status": "success"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    output = io.StringIO()
    assert run_observer(str(tmp_path), "demo", output=output, follow=False) == 0
    assert [json.loads(line)["sequence"] for line in output.getvalue().splitlines()] == [1, 3]

    resumed = io.StringIO()
    run_observer(str(tmp_path), "demo", after_sequence=1, output=resumed, follow=False)
    assert [json.loads(line)["sequence"] for line in resumed.getvalue().splitlines()] == [3]


def test_observer_text_format_is_compact(tmp_path):
    events_dir = tmp_path / "workspace" / "work_events"
    events_dir.mkdir(parents=True)
    (events_dir / "default.jsonl").write_text(
        json.dumps({"sequence": 1, "event_type": "tool.completed", "status": "success", "title": "Build", "target": "gui"}) + "\n",
        encoding="utf-8",
    )
    output = io.StringIO()
    run_observer(str(tmp_path), "default", output=output, format="text", follow=False)
    assert output.getvalue() == "[1] tool.completed success: Build gui\n"
