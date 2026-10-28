from copy import deepcopy

from architecture_diagram.analysis_audit import audit_analysis


def _evidence(path="src/app.py", line=1):
    return {"path": path, "line": line, "claim": "支持该结构或关系"}


def _fixtures():
    analysis = {
        "schemaVersion": 1,
        "project": {"name": "示例项目"},
        "coverage": {
            "analyzed": [{"scope": "主链路 Python 源文件", "fileCount": 1, "paths": ["src/app.py"], "codeLines": 3}],
            "notAnalyzed": [],
        },
        "stageA": {
            "status": "complete",
            "candidates": [
                {"id": "entry-candidate", "kind": "entry", "title": "请求入口候选", "evidence": [_evidence()]},
                {"id": "store-candidate", "kind": "storage", "title": "结果文件候选", "evidence": [_evidence(line=2)]},
            ],
        },
        "stageB": {
            "status": "complete",
            "layers": [
                {"id": "access", "role": "access", "name": "接入层", "reason": "接收外部请求"},
                {"id": "data", "role": "data_external", "name": "数据层", "reason": "持久化运行结果"},
            ],
            "modules": [
                {"id": "entry", "layerId": "access", "title": "请求入口", "responsibility": "接收任务请求", "evidence": [_evidence()]},
                {"id": "store", "layerId": "data", "title": "结果文件", "responsibility": "保存执行结果", "evidence": [_evidence(line=2)]},
            ],
            "candidateDisposition": [
                {"candidateId": "entry-candidate", "layerId": "access", "decision": "included", "moduleId": "entry"},
                {"candidateId": "store-candidate", "layerId": "data", "decision": "included", "moduleId": "store"},
            ],
            "densityReview": {
                "targetModulesPerLayer": {"min": 3, "max": 5},
                "mainGraphException": {"reason": "示例源代码仅能证明两个独立职责，未发现可拆分组件。", "evidence": [_evidence()]},
                "layerReviews": [
                    {"layerId": "access", "finalModuleIds": ["entry"], "outcome": "below_target_reviewed", "secondPassTriggered": True, "secondPassAction": "retain_after_review", "sourceCandidateIds": ["entry-candidate"], "reason": "入口职责由一个独立适配点承载，源码中没有第二种请求协议或会话建立组件。", "evidence": [_evidence()]},
                    {"layerId": "data", "finalModuleIds": ["store"], "outcome": "below_target_reviewed", "secondPassTriggered": True, "secondPassAction": "retain_after_review", "sourceCandidateIds": ["store-candidate"], "reason": "该示例只有一个结果持久化目标，未发现其他存储类型或数据用途。", "evidence": [_evidence(line=2)]},
                ],
                "moduleDecompositionReviews": [
                    {"moduleId": "entry", "signalsChecked": ["composite_actions", "state_and_control", "dispatch_and_execution", "multiple_technical_boundaries", "separate_data_purposes", "independent_lifecycle", "independent_relationships"], "signalsFound": [], "decision": "retain", "reason": "单一请求入口职责。", "evidence": [_evidence()]},
                    {"moduleId": "store", "signalsChecked": ["composite_actions", "state_and_control", "dispatch_and_execution", "multiple_technical_boundaries", "separate_data_purposes", "independent_lifecycle", "independent_relationships"], "signalsFound": [], "decision": "retain", "reason": "单一结果文件持久化职责。", "evidence": [_evidence(line=2)]},
                ],
            },
            "absentRoles": [{"role": "business", "reason": "该项目运行时未发现独立领域业务服务"}],
        },
        "stageC": {
            "status": "complete",
            "relations": [
                {"id": "writes-result", "from": "entry", "to": "store", "kind": "file_write", "label": "保存结果", "evidence": [_evidence(line=3)]},
            ],
        },
        "stageD": {
            "status": "complete",
            "paths": [{
                "id": "success", "title": "成功路径", "entry": "entry", "terminal": "store",
                "terminalType": "persisted", "nodeIds": ["entry", "store"],
                "relationIds": ["writes-result"], "status": "complete",
            }],
            "coverageReview": {
                "candidateInventoryReviewed": True,
                "moduleIngressEgressReviewed": True,
                "sideEffectsReviewed": True,
                "dispatchAndReturnReviewed": True,
                "moduleReviews": [
                    {"moduleId": "entry", "incomingRelationIds": [], "outgoingRelationIds": ["writes-result"], "sideEffectRelationIds": ["writes-result"], "branchesReviewed": True, "unmodeledActions": []},
                    {"moduleId": "store", "incomingRelationIds": ["writes-result"], "outgoingRelationIds": [], "sideEffectRelationIds": [], "branchesReviewed": True, "unmodeledActions": []},
                ],
                "iterations": 1,
                "backfilledRelationIds": [],
            },
        },
    }
    diagram = {
        "schemaVersion": 1, "id": "main", "title": "示例链路", "type": "architecture", "direction": "TB",
        "layers": [
            {"id": "access", "name": "接入层"},
            {"id": "data", "name": "数据层"},
        ],
        "nodes": [
            {"id": "entry", "layer": "access", "title": "请求入口", "desc": "接收任务请求", "evidence": [_evidence()]},
            {"id": "store", "layer": "data", "title": "结果文件", "desc": "保存执行结果", "evidence": [_evidence(line=2)]},
        ],
        "showEdgeLabels": False,
        "edges": [
            {"id": "e1", "from": "entry", "to": "store", "label": "", "kind": "other", "main": True, "relationIds": ["writes-result"], "evidence": [_evidence(line=3)]},
        ],
    }
    return analysis, diagram


def test_analysis_audit_accepts_complete_stage_outputs_and_connected_main_path():
    analysis, diagram = _fixtures()
    report = audit_analysis(analysis, diagram)
    assert report["passed"] is True
    assert report["counts"] == {
        "candidates": 2, "layers": 2, "modules": 2, "reviewedModules": 2, "relations": 1, "diagramEdges": 1,
        "densityReviewedModules": 2, "singletonLayerExceptions": 2,
        "mainGraphModules": 2, "mainGraphEdges": 1,
        "mainPaths": 1, "reachableModules": 2, "unreachableModules": [],
    }
    assert [item["moduleCount"] for item in report["layerDensity"]] == [1, 1]
    assert len([warning for warning in report["warnings"] if "低于" in warning]) == 2


def test_analysis_audit_rejects_unaccounted_candidates_and_relations_not_drawn():
    analysis, diagram = _fixtures()
    analysis["stageA"]["candidates"].append(
        {"id": "ignored", "kind": "tool", "title": "未处置工具", "evidence": [_evidence(line=4)]}
    )
    diagram["edges"].clear()
    report = audit_analysis(analysis, diagram)
    assert report["passed"] is False
    assert any("没有分层/归并/排除结论" in error for error in report["errors"])
    assert any("未进入任何主图/子图" in error for error in report["errors"])


def test_analysis_audit_rejects_broken_path_order_and_unmapped_diagram_edge():
    analysis, diagram = _fixtures()
    analysis["stageD"]["paths"][0]["relationIds"] = []
    diagram["edges"][0].pop("relationIds")
    report = audit_analysis(analysis, diagram)
    assert report["passed"] is False
    assert any("关系数必须等于节点数减一" in error for error in report["errors"])
    assert any("缺少 relationIds" in error for error in report["errors"])


def test_analysis_audit_checks_local_evidence_paths_and_line_ranges(tmp_path):
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("one\ntwo\n", encoding="utf-8")
    analysis, diagram = _fixtures()
    analysis = deepcopy(analysis)
    analysis["stageC"]["relations"][0]["evidence"][0]["line"] = 3
    report = audit_analysis(analysis, diagram, source_root=tmp_path)
    assert report["passed"] is False
    assert any("行号超出文件范围" in error for error in report["errors"])


def test_analysis_audit_requires_exact_per_module_edge_and_branch_review():
    analysis, diagram = _fixtures()
    analysis["stageD"]["coverageReview"]["moduleReviews"][0]["outgoingRelationIds"] = []
    analysis["stageD"]["coverageReview"]["moduleReviews"][1]["unmodeledActions"] = ["可能还有未记录的写入"]
    report = audit_analysis(analysis, diagram)
    assert report["passed"] is False
    assert any("outgoingRelationIds 与阶段 C 不一致" in error for error in report["errors"])
    assert any("unmodeledActions 必须为空" in error for error in report["errors"])


def test_analysis_audit_rejects_missing_module_review():
    analysis, diagram = _fixtures()
    analysis["stageD"]["coverageReview"]["moduleReviews"].pop()
    report = audit_analysis(analysis, diagram)
    assert report["passed"] is False
    assert any("缺少逐模块关系覆盖复核" in error for error in report["errors"])


def test_analysis_audit_requires_second_split_for_singleton_layer():
    analysis, diagram = _fixtures()
    analysis["stageB"]["densityReview"]["layerReviews"][0]["secondPassTriggered"] = False
    report = audit_analysis(analysis, diagram)
    assert report["passed"] is False
    assert any("低于软目标" in error for error in report["errors"])


def test_analysis_audit_requires_density_ids_to_match_main_graph():
    analysis, diagram = _fixtures()
    analysis["stageB"]["densityReview"]["layerReviews"][0]["finalModuleIds"] = ["store"]
    report = audit_analysis(analysis, diagram)
    assert report["passed"] is False
    assert any("必须与主图该层节点完全一致" in error for error in report["errors"])


def test_analysis_audit_rejects_unresolved_composite_module_signal():
    analysis, diagram = _fixtures()
    review = analysis["stageB"]["densityReview"]["moduleDecompositionReviews"][0]
    review["signalsFound"] = ["state_and_control"]
    review["decision"] = "split_again"
    report = audit_analysis(analysis, diagram)
    assert report["passed"] is False
    assert any("返回阶段 B" in error for error in report["errors"])


def test_analysis_audit_does_not_apply_architecture_density_gate_to_flow_diagrams():
    analysis, diagram = _fixtures()
    diagram["type"] = "flow"
    analysis["stageB"].pop("densityReview")
    report = audit_analysis(analysis, diagram)
    assert report["passed"] is True
    assert report["layerDensity"] == []
