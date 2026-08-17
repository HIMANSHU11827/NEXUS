from nexus.main_agent.drift import assess_direction


def test_direction_check_accepts_plan_with_objective_anchor():
    result = assess_direction(
        "repair the queue worker crash recovery",
        {"steps": [{"description": "inspect queue worker restart and crash recovery"}]},
    )
    assert result["drifted"] is False
    assert "queue" in result["matched_anchors"]


def test_direction_check_blocks_completely_unrelated_plan():
    result = assess_direction(
        "repair the queue worker crash recovery",
        {"steps": [{"description": "design a photo gallery landing page"}]},
    )
    assert result["drifted"] is True
    assert result["matched_anchors"] == []
    assert "queue" in result["missing_anchors"]


def test_direction_check_is_observability_only_for_partial_overlap():
    result = assess_direction(
        "deploy the queue worker crash recovery service",
        {"steps": [{"description": "inspect queue behavior"}]},
    )
    assert result["drifted"] is False
    assert result["confidence"] == "partial"
