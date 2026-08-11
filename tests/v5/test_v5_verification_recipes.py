import json

from orchestrators.v5.verification_recipes import detect_verification_recipe


def test_detects_node_phase_checks_from_package_scripts(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({
        "scripts": {"build": "vite build", "test": "vitest run", "lint": "eslint ."},
    }), encoding="utf-8")
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n", encoding="utf-8")
    recipe = detect_verification_recipe(tmp_path)
    assert recipe.source == "detected"
    assert [(item["phase"], item["command"]) for item in recipe.checks] == [
        ("build", "pnpm run build"), ("test", "pnpm run test"), ("lint", "pnpm run lint")
    ]


def test_manifest_recipe_is_preferred_and_read_only(tmp_path):
    manifest_dir = tmp_path / ".nexus_v5"
    manifest_dir.mkdir()
    manifest = manifest_dir / "verification.json"
    manifest.write_text(json.dumps({
        "name": "workspace checks", "kind": "custom",
        "checks": [{"phase": "test", "command": "pytest tests/unit -q"}],
    }), encoding="utf-8")
    recipe = detect_verification_recipe(tmp_path)
    assert recipe.source == "manifest"
    assert recipe.checks[0]["command"] == "pytest tests/unit -q"
    assert manifest.read_text(encoding="utf-8")


def test_detects_python_project_without_starting_or_mutating(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    recipe = detect_verification_recipe(tmp_path)
    assert recipe.kind == "python"
    assert recipe.checks == ({"phase": "test", "command": "python -m pytest"},)
