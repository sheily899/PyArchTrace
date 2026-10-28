from architecture_diagram import scanner
from architecture_diagram.scanner import scan_project


def test_scanner_extracts_imports_definitions_and_entrypoint(tmp_path):
    source = tmp_path / "app.py"
    source.write_text(
        "import json\nfrom pathlib import Path\n\n"
        "class Service:\n    pass\n\ndef main():\n    return Service()\n\n"
        "if __name__ == '__main__':\n    main()\n",
        encoding="utf-8",
    )
    facts = scan_project(tmp_path)
    assert facts["summary"]["python_files"] == 1
    assert facts["summary"]["code_lines"] == 11
    assert facts["modules"][0]["imports"][0]["module"] == "json"
    assert facts["modules"][0]["definitions"][0]["name"] == "Service"
    assert any(item["kind"] == "main_guard" for item in facts["entrypoints"])


def test_scanner_does_not_execute_project_code(tmp_path):
    marker = tmp_path / "must_not_exist.txt"
    (tmp_path / "danger.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n",
        encoding="utf-8",
    )
    scan_project(tmp_path)
    assert not marker.exists()


def test_scanner_skips_common_generated_directories(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_app.py").write_text("VALUE = 2\n", encoding="utf-8")
    facts = scan_project(tmp_path)
    assert [item["path"] for item in facts["modules"]] == ["src/app.py"]


def test_scanner_reports_inventory_and_truthful_analysis_coverage(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "app.py").write_text("def main():\n    pass\n", encoding="utf-8")
    (tmp_path / "tests" / "test_app.py").write_text("assert True\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"dependencies":{"example":"1"}}', encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("FROM python:3\n", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=must-not-leak\n", encoding="utf-8")

    facts = scan_project(tmp_path)

    assert facts["inventory"]["dependencyManifests"] == ["package.json"]
    assert "Dockerfile" in facts["inventory"]["containerFiles"]
    assert facts["coverage"]["analyzed"]["pythonFiles"] == ["src/app.py"]
    assert any("tests/" in item["path"] for item in facts["coverage"]["notAnalyzed"])
    serialized = str(facts)
    assert any(item["path"] == ".env" for item in facts["coverage"]["notAnalyzed"])
    assert "must-not-leak" not in serialized


def test_scanner_inventories_common_manifests_configs_entries_and_hidden_skips(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / "src" / "main.ts").write_text("export {}", encoding="utf-8")
    (tmp_path / "scripts" / "seed.py").write_text("print('skip')", encoding="utf-8")
    (tmp_path / "compose.dev.yaml").write_text("services: {}", encoding="utf-8")
    (tmp_path / "settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")

    facts = scan_project(tmp_path)

    assert "uv.lock" in facts["inventory"]["dependencyManifests"]
    assert "settings.json" in facts["inventory"]["configurationFiles"]
    assert "compose.dev.yaml" in facts["inventory"]["containerFiles"]
    assert "src/main.ts" in facts["inventory"]["entryFiles"]
    assert "scripts/" in facts["inventory"]["excludedPaths"]
    assert ".github/" in facts["inventory"]["excludedPaths"]
    assert [item["path"] for item in facts["modules"]] == []


def test_optimized_scanner_skips_generated_and_cache_directories_and_records_rule_version(tmp_path):
    (tmp_path / "src").mkdir()
    for dirname in ("outputs", "dist", "build", ".cache", "__pycache__", "node_modules", ".venv", ".git"):
        folder = tmp_path / dirname
        folder.mkdir()
        (folder / "hidden.py").write_text("SECRET = True\n", encoding="utf-8")
    (tmp_path / "src" / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")

    facts = scan_project(tmp_path, optimized=True)

    assert [module["path"] for module in facts["modules"]] == ["src/app.py"]
    assert facts["exclusionRulesVersion"] == "scan-exclusions-v2"
    assert facts["scanConfig"]["exclusionRulesVersion"] == facts["exclusionRulesVersion"]
    for dirname in ("outputs", "dist", "build", ".cache", "__pycache__", "node_modules", ".venv", ".git"):
        assert f"{dirname}/" in facts["inventory"]["excludedPaths"]
    assert "outputs" in facts["scanConfig"]["excludedDirectoryNames"]
    assert "SECRET" not in str(facts)


def test_scanner_can_include_a_default_excluded_directory(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "outputs").mkdir()
    (tmp_path / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "outputs" / "generated.py").write_text("VALUE = 2\n", encoding="utf-8")

    facts = scan_project(tmp_path, included_dirs={"outputs"}, optimized=True)

    assert [module["path"] for module in facts["modules"]] == ["outputs/generated.py", "src/app.py"]
    assert "outputs" not in facts["scanConfig"]["excludedDirectoryNames"]
    assert facts["scanConfig"]["includedOverrides"] == ["outputs"]
    assert "outputs/" not in facts["inventory"]["excludedPaths"]


def test_scanner_discovers_inventory_and_python_files_in_one_tree_walk(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    real_walk = scanner.os.walk
    calls = 0

    def counted_walk(*args, **kwargs):
        nonlocal calls
        calls += 1
        yield from real_walk(*args, **kwargs)

    monkeypatch.setattr(scanner.os, "walk", counted_walk)
    facts = scan_project(tmp_path, optimized=True)

    assert calls == 1
    assert facts["inventory"]["fileCount"] == 1
    assert facts["summary"]["python_files"] == 1


def test_compatibility_scanner_remains_default(tmp_path):
    (tmp_path / "outputs").mkdir()
    (tmp_path / "outputs" / "kept.py").write_text("VALUE = 1\n", encoding="utf-8")
    facts = scan_project(tmp_path)

    assert [module["path"] for module in facts["modules"]] == ["outputs/kept.py"]
    assert "scanConfig" not in facts
