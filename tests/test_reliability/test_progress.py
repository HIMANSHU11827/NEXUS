"""Tests for reliability.progress: stall detection and persistence."""

from reliability.progress import ProgressTracker, StallSignal


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class TestProgressTracker:
    def test_no_signal_while_progressing(self):
        clock = FakeClock()
        tracker = ProgressTracker(max_idle_s=60.0, clock=clock)
        for _ in range(10):
            tracker.record({"kind": "state_change", "signature": "s"})
            clock.advance(10)
        assert tracker.check() is None

    def test_idle_stall(self):
        clock = FakeClock()
        tracker = ProgressTracker(max_idle_s=60.0, clock=clock)
        tracker.record({"kind": "artifact", "signature": "a1"})
        clock.advance(61.0)
        signal = tracker.check()
        assert signal is not None
        assert signal.kind == "idle"
        assert "61s" in signal.detail or "60s" in signal.detail

    def test_never_started_is_not_stall(self):
        tracker = ProgressTracker(max_idle_s=1.0)
        assert tracker.check() is None

    def test_repeated_identical_tool_call(self):
        tracker = ProgressTracker(max_idle_s=999.0)
        for _ in range(4):
            tracker.record({"kind": "tool_call", "signature": "call-x", "status": "success"})
        signal = tracker.check()
        assert signal is not None
        assert signal.kind == "repeated_tool_call"

    def test_new_tool_call_is_progress(self):
        tracker = ProgressTracker(max_idle_s=999.0)
        tracker.record({"kind": "tool_call", "signature": "a", "status": "success"})
        tracker.record({"kind": "tool_call", "signature": "b", "status": "success"})
        assert tracker.check() is None

    def test_repeated_errors(self):
        tracker = ProgressTracker(max_idle_s=999.0)
        for _ in range(4):
            tracker.record({"kind": "error", "signature": "ERR-42"})
        signal = tracker.check()
        assert signal is not None
        assert signal.kind == "repeated_error"

    def test_error_precedes_idle_signal(self):
        clock = FakeClock()
        tracker = ProgressTracker(max_idle_s=10.0, clock=clock)
        for _ in range(4):
            tracker.record({"kind": "error", "signature": "E"})
            clock.advance(0.1)
        signal = tracker.check()
        assert signal.kind == "repeated_error"

    def test_context_exhaustion_signal_after_repeated_compactions(self):
        tracker = ProgressTracker(max_idle_s=999.0)
        for _ in range(3):
            tracker.record({"kind": "compaction", "signature": "prompt_too_long_retry"})
        signal = tracker.check()
        assert signal is not None
        assert signal.kind == "context_exhaustion"
        assert "compacted 3 times" in signal.detail

    def test_context_exhaustion_below_limit_is_not_a_stall(self):
        tracker = ProgressTracker(max_idle_s=999.0)
        tracker.record({"kind": "compaction", "signature": "prompt_too_long_retry"})
        assert tracker.check() is None

    def test_verified_success_resets_context_exhaustion(self):
        tracker = ProgressTracker(max_idle_s=999.0)
        for _ in range(3):
            tracker.record({"kind": "compaction", "signature": "prompt_too_long_retry"})
        tracker.record({"kind": "tool_call", "signature": "probe", "status": "success"})
        assert tracker.check() is None

    def test_context_exhaustion_persists_across_restart(self, tmp_path):
        path = str(tmp_path / "progress-compaction.json")
        tracker = ProgressTracker(max_idle_s=999.0, persist_path=path)
        tracker.record({"kind": "compaction", "signature": "prompt_too_long_retry"})
        tracker.record({"kind": "compaction", "signature": "provider_recovery"})
        loaded = ProgressTracker(max_idle_s=999.0, persist_path=path)
        loaded.record({"kind": "compaction", "signature": "prompt_too_long_retry"})
        signal = loaded.check()
        assert signal is not None
        assert signal.kind == "context_exhaustion"

    def test_unknown_kinds_ignored(self):
        tracker = ProgressTracker(max_idle_s=1.0)
        tracker.record({"kind": "whatever"})
        tracker.record(None)
        tracker.record("string")
        assert tracker.check() is None

    def test_recent_events_bounded(self):
        tracker = ProgressTracker(max_idle_s=999.0, event_window=10)
        for i in range(20):
            tracker.record({"kind": "state_change", "signature": f"s{i}"})
        assert len(tracker.recent_events(limit=50)) == 10

    def test_snapshot_restore(self):
        tracker = ProgressTracker(max_idle_s=999.0)
        tracker.record({"kind": "state_change", "signature": "s1"})
        snapshot = tracker.snapshot()
        restored = ProgressTracker(max_idle_s=999.0)
        restored.restore(snapshot)
        assert restored.last_progress() == tracker.last_progress()
        assert restored.event_count() == tracker.event_count()

    def test_reset(self):
        tracker = ProgressTracker(max_idle_s=1.0)
        tracker.record({"kind": "artifact", "signature": "a"})
        tracker.reset()
        assert tracker.last_progress() is None
        assert tracker.check() is None

    def test_mark_progress(self):
        clock = FakeClock()
        tracker = ProgressTracker(max_idle_s=10.0, clock=clock)
        clock.advance(50)
        tracker.mark_progress()
        assert tracker.check() is None

    def test_persistence(self, tmp_path):
        path = str(tmp_path / "progress.json")
        tracker = ProgressTracker(max_idle_s=999.0, persist_path=path)
        tracker.record({"kind": "state_change", "signature": "s1"})
        tracker.record({"kind": "tool_call", "signature": "t1", "status": "success"})
        loaded = ProgressTracker(max_idle_s=999.0, persist_path=path)
        assert loaded.event_count() == 2
        assert loaded.last_progress() == tracker.last_progress()

    def test_corrupt_persistence_tolerated(self, tmp_path):
        path = tmp_path / "progress.json"
        path.write_text("{broken", encoding="utf-8")
        tracker = ProgressTracker(max_idle_s=999.0, persist_path=str(path))
        assert tracker.check() is None
        assert tracker.event_count() == 0


class TestStallSignal:
    def test_fields(self):
        signal = StallSignal(kind="idle", detail="d", since=1.0, recent_events=[{"k": "v"}])
        assert signal.kind == "idle"
        assert signal.detail == "d"
        assert signal.since == 1.0
        assert signal.recent_events == [{"k": "v"}]