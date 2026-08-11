from pathlib import Path


def test_main_chat_has_explicit_timed_out_status_label():
    source = Path(__file__).parents[3].joinpath("gui", "src", "components", "MainChat.tsx").read_text(encoding="utf-8")
    assert "case 'timed_out':" in source
    assert "return { label: 'Timed out', active: false }" in source
