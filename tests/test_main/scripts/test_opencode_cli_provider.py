from subprocess import CompletedProcess

from providers.opencode_cli import OpenCodeCLIProvider


def test_opencode_cli_provider_cleans_terminal_footer(monkeypatch):
    provider = object.__new__(OpenCodeCLIProvider)
    provider._cli_path = "opencode.cmd"
    monkeypatch.setattr(
        "providers.opencode_cli.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(args[0], 0, "NEXUS OK\n\x1b[0m\n> plan · free\n", ""),
    )

    assert provider.generate(messages=[{"role": "user", "content": "hello"}]) == "NEXUS OK"


def test_opencode_cli_provider_reports_process_failure(monkeypatch):
    provider = object.__new__(OpenCodeCLIProvider)
    provider._cli_path = "opencode.cmd"
    monkeypatch.setattr(
        "providers.opencode_cli.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(args[0], 1, "", "not authenticated"),
    )

    assert provider.generate(prompt="hello").startswith("Error: OpenCode CLI failed: not authenticated")
