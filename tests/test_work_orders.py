import json
from pathlib import Path

import pytest

from architecture_diagram.work_orders import analysis_rules_path, build_work_order


ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_SCHEMA = json.loads((ROOT / "schemas/analysis.schema.json").read_text(encoding="utf-8"))
DIAGRAM_SCHEMA = json.loads((ROOT / "schemas/diagram.schema.json").read_text(encoding="utf-8"))


@pytest.fixture
def facts():
    return {
        "formatVersion": 1,
        "project": {"name": "测试项目"},
        "summary": {"python_files": 3, "code_lines": 72},
        "coverage": {"analyzed": {"fileCount": 3}, "notAnalyzed": []},
        "inventory": {
            "directories": ["src/", "src/api/", "src/other/"],
            "fileCount": 7,
            "dependencyManifests": ["pyproject.toml"],
            "configurationFiles": ["settings.yaml"],
            "containerFiles": [],
            "entryFiles": ["src/api/app.py"],
            "nonPythonFiles": ["README.md"],
            "excludedPaths": ["tests/"],
            "sensitivePaths": [".env"],
        },
        "modules": [
            {"path": "src/core/intent.py", "module": "src.core.intent", "line_count": 20,
             "imports": [{"module": "src.shared.types", "line": 1}],
             "definitions": [{"name": "Intent", "kind": "class", "line": 3, "end_line": 20}],
             "entrypoints": []},
            {"path": "src/api/app.py", "module": "src.api.app", "line_count": 32,
             "imports": [{"module": "src.core.intent", "line": 2}],
             "definitions": [{"name": "handle", "kind": "function", "line": 5, "end_line": 32}],
             "entrypoints": [{"kind": "conventional_function", "name": "main", "line": 5}]},
            {"path": "src/other/report.py", "module": "src.other.report", "line_count": 20,
             "imports": [], "definitions": [{"name": "Report", "kind": "class", "line": 2, "end_line": 20}],
             "entrypoints": []},
        ],
        "entrypoints": [{"path": "src/api/app.py", "kind": "conventional_function", "name": "main", "line": 5}],
        "limitations": ["AST 仅作导航索引"],
    }


@pytest.fixture
def analysis():
    return {
        "schemaVersion": 1,
        "project": {"name": "测试项目"},
        "coverage": {"analyzed": [], "notAnalyzed": []},
        "stageA": {
            "status": "complete",
            "candidates": [
                {"id": "intent-candidate", "kind": "service", "title": "意图识别候选",
                 "evidence": [{"path": "src/core/intent.py", "line": 3, "claim": "识别意图"}]},
                {"id": "api-candidate", "kind": "entry", "title": "请求入口候选",
                 "evidence": [{"path": "src/api/app.py", "line": 5, "claim": "接收请求"}]},
            ],
        },
        "stageB": {
            "status": "complete",
            "layers": [{"id": "access", "role": "access", "name": "接入层", "reason": "接收请求"}],
            "modules": [
                {"id": "intent", "layerId": "capability", "title": "意图识别", "responsibility": "识别业务意图",
                 "evidence": [{"path": "src/core/intent.py", "line": 3, "claim": "识别意图"}]},
                {"id": "api", "layerId": "access", "title": "请求入口", "responsibility": "接收请求",
                 "evidence": [{"path": "src/api/app.py", "line": 5, "claim": "接收请求"}]},
                {"id": "report", "layerId": "business", "title": "报表生成", "responsibility": "组织报表",
                 "evidence": [{"path": "src/other/report.py", "line": 2, "claim": "生成报表"}]},
            ],
            "candidateDisposition": [],
        },
        "stageC": {
            "status": "complete",
            "relations": [
                {"id": "api-intent", "from": "api", "to": "intent", "kind": "function_call",
                 "label": "识别请求", "evidence": [{"path": "src/api/app.py", "line": 15, "claim": "调用识别"}]},
                {"id": "report-intent", "from": "report", "to": "intent", "kind": "function_call",
                 "label": "读取分类", "evidence": [{"path": "src/other/report.py", "line": 8, "claim": "调用识别"}]},
            ],
        },
    }


def _json_section(prompt, heading, next_heading):
    section = prompt.split(heading, 1)[1].split(next_heading, 1)[0]
    return json.loads(section.split("```json", 1)[1].split("```", 1)[0])


def test_full_work_order_remains_compatible_and_uses_authoritative_rules(facts):
    prompt = build_work_order(facts=facts, analysis_schema=ANALYSIS_SCHEMA,
                              diagram_schema=DIAGRAM_SCHEMA)

    assert "A-D 阶段分析规则（唯一权威来源）" in prompt
    assert "主链路完整性校验" in prompt
    assert "sensitivePaths" in prompt  # full legacy mode retains the complete facts object
    assert "diagram.schema.json" in prompt
    assert "analysis.schema.json" in prompt
    assert "analysis-reports analysis.json" in prompt


def test_skill_and_work_orders_have_one_authoritative_a_to_d_rule_source(facts, analysis):
    rules = analysis_rules_path().read_text(encoding="utf-8").strip()
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    full = build_work_order(facts=facts, analysis_schema=ANALYSIS_SCHEMA,
                            diagram_schema=DIAGRAM_SCHEMA)

    assert all(f"#### 阶段 {stage}：" in rules for stage in "ABCD")
    assert all(f"#### 阶段 {stage}：" not in skill for stage in "ABCD")
    assert rules in full

    for stage in "ABCD":
        scoped = build_work_order(facts=facts, analysis_schema=ANALYSIS_SCHEMA,
                                  diagram_schema=DIAGRAM_SCHEMA, stage=stage,
                                  slim=True, analysis=analysis if stage != "A" else None,
                                  module_id="intent" if stage == "C" else None)
        assert f"#### 阶段 {stage}：" in scoped
        assert all(f"#### 阶段 {other}：" not in scoped for other in "ABCD" if other != stage)


def test_stage_a_work_order_filters_schema_and_records_fact_scope(facts):
    prompt = build_work_order(facts=facts, analysis_schema=ANALYSIS_SCHEMA,
                              diagram_schema=DIAGRAM_SCHEMA, stage="A", slim=True)

    assert "阶段 A：模块候选提取" in prompt
    assert "阶段 B：分层归类" not in prompt
    assert '"stageA"' in prompt
    assert '"stageB"' not in prompt
    assert "diagram.schema.json" in prompt  # explicitly listed as omitted, not injected
    assert '"sensitivePathCount": 1' in prompt
    assert '"sensitivePaths"' not in prompt
    assert '"factsOmitted"' in prompt
    assert "modules[*].path/module/imports/definitions/entrypoints" in prompt


def test_stage_b_includes_only_candidate_evidence_ast(facts, analysis):
    prompt = build_work_order(facts=facts, analysis_schema=ANALYSIS_SCHEMA,
                              diagram_schema=DIAGRAM_SCHEMA, stage="B", analysis=analysis, slim=True)

    assert "阶段 B：分层归类与模块定稿" in prompt
    assert "src/core/intent.py" in prompt
    assert "src/api/app.py" in prompt
    assert "src/other/report.py" not in prompt
    assert "未被阶段 A 候选证据引用的 modules[*] AST 详情" in prompt
    assert '"stageA"' in prompt
    assert '"stageB"' in prompt
    context = _json_section(prompt, "## 必要的已有 analysis 上下文", "## 本阶段 JSON Schema")
    assert "stageC" not in context


def test_stage_c_scopes_ast_details_to_target_and_direct_import_neighbors(facts, analysis):
    prompt = build_work_order(facts=facts, analysis_schema=ANALYSIS_SCHEMA,
                              diagram_schema=DIAGRAM_SCHEMA, stage="C", analysis=analysis,
                              module_id="intent", slim=True)

    assert '"moduleId": "intent"' in prompt
    assert "src/core/intent.py" in prompt
    assert "src/api/app.py" in prompt
    assert "src/other/report.py" in prompt  # path index stays visible; unrelated AST details do not
    selected_facts = _json_section(prompt, "## 筛选后的结构索引 facts", "## 必要的已有 analysis 上下文")
    assert {item["path"] for item in selected_facts["modules"]} == {
        "src/core/intent.py", "src/api/app.py"
    }
    assert {item["path"] for item in selected_facts["moduleIndex"]} == {
        "src/core/intent.py", "src/api/app.py", "src/other/report.py"
    }
    assert "与 intent 相连的关系（2 条）" in prompt
    assert "stageC" in prompt


def test_stage_d_keeps_graph_context_but_omits_ast_details(facts, analysis):
    analysis["stageD"] = {"status": "complete", "paths": [], "coverageReview": {}}
    prompt = build_work_order(facts=facts, analysis_schema=ANALYSIS_SCHEMA,
                              diagram_schema=DIAGRAM_SCHEMA, stage="D", analysis=analysis, slim=True)

    assert "阶段 D：主链路完整性校验" in prompt
    assert '"stageA"' in prompt and '"stageB"' in prompt and '"stageC"' in prompt and '"stageD"' in prompt
    assert "modules[*].imports/definitions/entrypoints AST 详情" in prompt
    selected_facts = _json_section(prompt, "## 筛选后的结构索引 facts", "## 必要的已有 analysis 上下文")
    assert "modules" not in selected_facts
    assert len(selected_facts["moduleIndex"]) == 3


def test_stage_c_requires_single_module_and_analysis(facts):
    with pytest.raises(ValueError, match="必须提供 --analysis"):
        build_work_order(facts=facts, analysis_schema=ANALYSIS_SCHEMA,
                         diagram_schema=DIAGRAM_SCHEMA, stage="C", slim=True)
