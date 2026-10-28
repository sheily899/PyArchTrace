import json
from argparse import Namespace

from architecture_diagram import cli
from architecture_diagram.cli import _cmd_prompt


def test_abstract_prompt_requires_evidence_based_module_decomposition(tmp_path):
    facts_path = tmp_path / "facts.json"
    facts_path.write_text(json.dumps({"summary": {}, "files": []}), encoding="utf-8")
    output_path = tmp_path / "abstract.md"

    assert _cmd_prompt(Namespace(facts=str(facts_path), output=str(output_path))) == 0

    prompt = output_path.read_text(encoding="utf-8")
    assert "唯一权威来源" in prompt
    assert "references/analysis-stages.md" in prompt
    assert "analysis-reports analysis.json" in prompt
    assert "modules.md" in prompt
    assert "阶段 A：模块候选提取" in prompt
    assert "阶段 D：主链路完整性校验" in prompt
    assert "coverageReview.moduleReviews" in prompt
    assert "unmodeledActions" in prompt
    assert "schemas/analysis.schema.json" in prompt
    assert "完整兼容" not in prompt


def test_audit_analysis_appends_diagram_errors_when_audit_report_has_no_error_list(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_read_json", lambda _: {"type": "sequence"})
    monkeypatch.setattr(cli, "audit_analysis", lambda *_args, **_kwargs: {"passed": False, "warnings": []})
    monkeypatch.setattr(cli, "validate_diagram", lambda _diagram: ["bad edge"])

    result = cli._cmd_audit_analysis(Namespace(
        analysis="analysis.json", diagram="diagram.json", facts=None,
        source_root=None, layout_backend="builtin", output=None,
    ))

    assert result == 2
    report = json.loads(capsys.readouterr().out)
    assert report["errors"] == ["diagram: bad edge"]


def test_scan_cli_reports_exclusion_paths_and_supports_include_override(tmp_path, capsys):
    from architecture_diagram.cli import _cmd_scan

    (tmp_path / "src").mkdir()
    (tmp_path / "outputs").mkdir()
    (tmp_path / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "outputs" / "generated.py").write_text("VALUE = 2\n", encoding="utf-8")
    output = tmp_path / "facts.json"

    assert _cmd_scan(Namespace(project=str(tmp_path), output=str(output), exclude_dir=None,
                               include_dir=None, optimized_scan=True)) == 0
    console = capsys.readouterr().out
    facts = json.loads(output.read_text(encoding="utf-8"))
    assert "优化模式（scan-exclusions-v2）" in console
    assert "实际跳过路径：outputs/" in console
    assert facts["inventory"]["excludedPaths"] == ["outputs/"]


def test_scan_cli_include_dir_reopens_default_exclusion(tmp_path, capsys):
    from architecture_diagram.cli import build_parser

    (tmp_path / "outputs").mkdir()
    (tmp_path / "outputs" / "generated.py").write_text("VALUE = 2\n", encoding="utf-8")
    output = tmp_path / "facts.json"
    args = build_parser().parse_args(["scan", str(tmp_path), "-o", str(output), "--optimized-scan",
                                      "--include-dir", "outputs"])

    assert args.func(args) == 0
    facts = json.loads(output.read_text(encoding="utf-8"))
    assert [module["path"] for module in facts["modules"]] == ["outputs/generated.py"]
    assert facts["scanConfig"]["includedOverrides"] == ["outputs"]
    assert "outputs/" not in facts["inventory"]["excludedPaths"]


def test_layout_cache_is_opt_in_and_exposed_on_validation_command():
    from architecture_diagram.cli import build_parser

    parser = build_parser()
    default = parser.parse_args(["validate", "diagram.json"])
    enabled = parser.parse_args(["validate", "diagram.json", "--reuse-layout-cache"])

    assert default.reuse_layout_cache is False
    assert enabled.reuse_layout_cache is True


def test_slim_work_order_is_opt_in_and_accepts_stage_scope():
    from architecture_diagram.cli import build_parser

    parser = build_parser()
    default = parser.parse_args(["abstract-prompt", "facts.json", "-o", "work.md"])
    stage = parser.parse_args(["abstract-prompt", "facts.json", "-o", "work.md",
                               "--slim-input", "--stage", "A"])

    assert default.slim_input is False
    assert default.stage is None
    assert stage.slim_input is True
    assert stage.stage == "A"


def test_analysis_reports_command_writes_three_derived_files(tmp_path, capsys):
    from architecture_diagram.cli import build_parser

    analysis_path = tmp_path / "analysis.json"
    analysis_path.write_text(json.dumps({
        "project": {"name": "命令测试"},
        "stageB": {"layers": [{"id": "access", "name": "接入层"}],
                   "modules": [{"id": "entry", "layerId": "access", "title": "请求入口",
                                "evidence": [{"path": "app.py", "line": 1}]}]},
        "stageC": {"relations": []},
        "stageD": {"paths": [{"id": "p1", "entry": "entry", "terminal": "entry",
                               "nodeIds": ["entry"], "relationIds": []}]},
    }, ensure_ascii=False), encoding="utf-8")
    out_dir = tmp_path / "reports"
    args = build_parser().parse_args(["analysis-reports", str(analysis_path), "-o", str(out_dir)])

    assert args.func(args) == 0
    assert {path.name for path in out_dir.iterdir()} == {"modules.md", "relations.md", "main-paths.md"}
    assert "请求入口" in (out_dir / "modules.md").read_text(encoding="utf-8")
    assert "p1" in (out_dir / "main-paths.md").read_text(encoding="utf-8")
    assert "modules.md" in capsys.readouterr().out
