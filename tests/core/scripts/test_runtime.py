import os

import pytest

from nexus.runtime import (
    build_chat_request,
    build_resume_prompt,
    parse_max_tokens,
    safe_session_id,
    safe_turn_id,
    session_file_path,
)


def test_safe_session_and_turn_ids_are_shared_runtime_contract():
    assert safe_session_id("../bad/name.json") == "name"
    assert safe_session_id("...") == "default"
    assert safe_turn_id("run id/with spaces!") == "run_id_with_spaces_"


def test_session_file_path_stays_inside_sessions_dir(tmp_path):
    path = session_file_path(str(tmp_path), "../evil", ".json")

    assert path == os.path.join(str(tmp_path), "evil.json")


def test_parse_max_tokens_rejects_non_integer():
    with pytest.raises(ValueError, match="max_tokens must be an integer"):
        parse_max_tokens("many")


def test_build_chat_request_normalizes_shared_chat_fields():
    request = build_chat_request(
        {
            "prompt": "  hello  ",
            "session_id": "../session.json",
            "provider": "Open AI",
            "model": "gpt-test",
            "max_tokens": "123",
            "turn_id": "turn 1!",
        },
        default_source="test",
    )

    assert request.prompt == "hello"
    assert request.session_id == "session"
    assert request.provider == "open_ai"
    assert request.model == "gpt-test"
    assert request.max_tokens == 123
    assert request.turn_id == "turn_1_"
    assert request.source == "test"


def test_build_chat_request_rejects_empty_prompt():
    with pytest.raises(ValueError, match="prompt is required"):
        build_chat_request({"prompt": "   "})


def test_build_resume_prompt_is_shared_and_noops_without_context():
    assert build_resume_prompt("continue", "") == "continue"
    prompt = build_resume_prompt("continue", "unfinished phase")
    assert prompt.startswith("continue\n\n[NEXUS_RESUME_CONTEXT]")
    assert "unfinished phase" in prompt
    assert prompt.endswith("[/NEXUS_RESUME_CONTEXT]")
