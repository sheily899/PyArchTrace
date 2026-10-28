import json
import sys
from argparse import Namespace

from architecture_diagram import cli
from architecture_diagram.versioning import version_mismatches


def test_source_skill_versions_match_runtime():
    assert version_mismatches() == []


def test_validate_fails_when_skill_version_is_stale(tmp_path, simple_diagram, monkeypatch, capsys):
    diagram_path = tmp_path / "diagram.json"
    diagram_path.write_text(json.dumps(simple_diagram), encoding="utf-8")
    skill_path = tmp_path / "SKILL.md"
    skill_path.write_text(
        "<!-- architecture-diagram-version: renderer=architecture-renderer-v0; layout=architecture-swimlane-v9 -->",
        encoding="utf-8",
    )

    monkeypatch.setattr(sys, "argv", ["architecture-diagram", "validate", str(diagram_path),
                                       "--check-versions", "--skill-file", str(skill_path)])

    assert cli.main() == 2
    output = capsys.readouterr().out
    assert "Skill 渲染器版本为 architecture-renderer-v0" in output
    assert "Skill 布局版本为 architecture-swimlane-v9" in output


def test_version_check_remains_explicit_opt_in(simple_diagram, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_read_json", lambda _: simple_diagram)
    monkeypatch.setattr(cli, "version_mismatches", lambda _path=None: ["stale version"])

    assert cli._cmd_validate(Namespace(diagram="diagram.json", check_versions=False, skill_file=None)) == 0
    assert "图数据校验通过" in capsys.readouterr().out
