from datetime import timezone

from nexus.main_agent.core import V5TurnContext


def test_v5_turn_timestamps_are_timezone_aware_utc():
    turn = V5TurnContext(turn_id="turn", session_id="session", user_input="work")

    assert turn.start_time.tzinfo is timezone.utc
