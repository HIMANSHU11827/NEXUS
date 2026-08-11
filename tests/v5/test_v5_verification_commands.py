from orchestrators.v5.verification_commands import classify_verification_command
from orchestrators.v5.verification import V5Verifier
import asyncio


def test_recognized_commands_produce_bounded_verification_evidence():
    evidence = classify_verification_command(
        "python -m pytest tests/unit -q", exit_code=0,
        output="Bearer secret-token should be redacted",
    )
    assert evidence["canonical_command"] == "pytest"
    assert evidence["kind"] == "test"
    assert evidence["status"] == "passed"
    assert "secret-token" not in evidence["output_summary"]


def test_unrecognized_or_chained_commands_are_not_verification():
    assert classify_verification_command("echo hello", exit_code=0) is None
    assert classify_verification_command("pytest -q && echo done", exit_code=0) is None
    assert classify_verification_command("python script.py", exit_code=0) is None
    assert classify_verification_command("pytest -q") is None
    assert classify_verification_command("pytest -q | tee result.txt", exit_code=0) is None


def test_configured_command_can_be_explicitly_classified():
    evidence = classify_verification_command(
        "./check-project --fast", exit_code=2,
        configured_commands=["./check-project"],
    )
    assert evidence["kind"] == "configured"
    assert evidence["status"] == "failed"
    assert evidence["exit_code"] == 2


def test_v5_verifier_uses_trusted_action_exit_code():
    verifier = V5Verifier()
    verifier.root_dir = "."
    result = asyncio.run(verifier._verify_result({
        "actions": [{
            "tool": "terminal", "params": {"command": "pytest -q"},
            "output": "tests passed", "success": True, "exit_code": 0,
        }],
    }))
    assert result["actions"][0]["verification_command"]["canonical_command"] == "pytest"
