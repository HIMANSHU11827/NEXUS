import io
import zipfile
from pathlib import Path

import pytest


def _archive(*entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in entries:
            archive.writestr(name, content)
    buffer.seek(0)
    return zipfile.ZipFile(buffer, "r")


def test_safe_zip_extraction_preserves_nested_files(tmp_path):
    from apps.web.api import _safe_extract_zip

    with _archive(("repo/src/main.py", "print('ok')")) as archive:
        _safe_extract_zip(archive, str(tmp_path / "extract"))

    assert (tmp_path / "extract" / "repo" / "src" / "main.py").read_text() == "print('ok')"


@pytest.mark.parametrize("name", ["../escape.txt", "repo/../../escape.txt", "..\\escape.txt"])
def test_safe_zip_extraction_rejects_traversal(tmp_path, name):
    from apps.web.api import _safe_extract_zip

    with _archive((name, "escape")) as archive:
        with pytest.raises(RuntimeError, match="traversal|absolute"):
            _safe_extract_zip(archive, str(tmp_path / "extract"))

    assert not (tmp_path / "escape.txt").exists()


def test_forced_plugin_install_preserves_existing_on_download_failure(monkeypatch, tmp_path):
    import apps.web.api as api

    monkeypatch.setenv("NEXUS_ALLOW_UNVERIFIED_PLUGIN_INSTALL", "1")
    monkeypatch.setattr(api, "_ROOT", str(tmp_path))
    target = tmp_path / "plugins" / "demo"
    target.mkdir(parents=True)
    (target / "existing.txt").write_text("keep", encoding="utf-8")

    def fail_git(*_args, **_kwargs):
        raise RuntimeError("git unavailable")

    monkeypatch.setattr(api.subprocess, "run", fail_git)
    monkeypatch.setattr(api, "_download_github_zip", lambda *_args: (_ for _ in ()).throw(RuntimeError("zip unavailable")))

    with pytest.raises(Exception) as raised:
        api.install_plugin_from_source("https://github.com/acme/demo.git", force=True)

    assert getattr(raised.value, "status_code", None) == 500
    assert (target / "existing.txt").read_text(encoding="utf-8") == "keep"
    assert not list((tmp_path / "plugins").glob(".demo.*"))


def test_plugin_install_promotes_staged_source(monkeypatch, tmp_path):
    import apps.web.api as api

    monkeypatch.setenv("NEXUS_ALLOW_UNVERIFIED_PLUGIN_INSTALL", "1")
    monkeypatch.setattr(api, "_ROOT", str(tmp_path))

    def fake_git(command, **_kwargs):
        staging = Path(command[-1])
        staging.mkdir(parents=True)
        (staging / "source.py").write_text("new", encoding="utf-8")

    monkeypatch.setattr(api.subprocess, "run", fake_git)
    result = api.install_plugin_from_source("https://github.com/acme/demo.git")

    target = tmp_path / "plugins" / "demo"
    assert result["path"] == str(target)
    assert (target / "source.py").read_text(encoding="utf-8") == "new"
    assert (target / ".codex-plugin" / "plugin.json").exists()
    assert not list((tmp_path / "plugins").glob(".demo.*"))


def test_artifact_archive_path_rejects_symlink_escape(tmp_path):
    from apps.web.api import _safe_artifact_file_path

    root = tmp_path / "artifacts"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = root / "linked.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this platform")

    assert _safe_artifact_file_path(str(root), str(link)) is None
