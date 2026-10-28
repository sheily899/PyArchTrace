from architecture_diagram.analysis_reports import generate_analysis_reports


def _analysis():
    return {
        "project": {"name": "微型系统"},
        "stageA": {"candidates": [
            {"id": "request-candidate", "title": "请求候选"},
            {"id": "store-candidate", "title": "存储候选"},
        ]},
        "stageB": {
            "layers": [
                {"id": "access", "role": "access", "name": "接入层", "reason": "接收请求"},
                {"id": "data", "role": "data_external", "name": "数据层", "reason": "保存结果"},
            ],
            "modules": [
                {"id": "request", "layerId": "access", "title": "请求入口", "responsibility": "接收任务请求",
                 "evidence": [{"path": "src/app.py", "line": 4, "claim": "接收外部输入"}]},
                {"id": "store", "layerId": "data", "title": "结果存储", "responsibility": "保存运行结果",
                 "evidence": [{"path": "src/store.py", "line": 8, "claim": "写入结果文件"}]},
            ],
            "candidateDisposition": [
                {"candidateId": "request-candidate", "decision": "included", "moduleId": "request"},
                {"candidateId": "store-candidate", "decision": "included", "moduleId": "store"},
            ],
            "densityReview": {
                "layerReviews": [{"layerId": "access", "outcome": "below_target_reviewed", "reason": "只有一个请求入口"}],
                "moduleDecompositionReviews": [{"moduleId": "request", "decision": "retain", "reason": "职责单一"}],
            },
            "absentRoles": [{"role": "business", "reason": "未发现独立业务服务"}],
        },
        "stageC": {"relations": [
            {"id": "writes", "from": "request", "to": "store", "kind": "file_write", "label": "保存结果",
             "condition": "处理成功", "evidence": [{"path": "src/app.py", "line": 11, "claim": "写入输出文件"}]},
        ]},
        "stageD": {
            "paths": [{"id": "success", "title": "成功路径", "entry": "request", "terminal": "store",
                       "terminalType": "persisted", "nodeIds": ["request", "store"],
                       "relationIds": ["writes"], "status": "complete"}],
            "coverageReview": {
                "candidateInventoryReviewed": True,
                "moduleIngressEgressReviewed": True,
                "sideEffectsReviewed": True,
                "dispatchAndReturnReviewed": True,
                "iterations": 2,
                "backfilledRelationIds": ["writes"],
                "moduleReviews": [{"moduleId": "request", "incomingRelationIds": [],
                                   "outgoingRelationIds": ["writes"], "sideEffectRelationIds": ["writes"],
                                   "branchesReviewed": True, "unmodeledActions": []}],
            },
        },
    }


def test_analysis_reports_include_all_stage_facts_and_source_evidence():
    reports = generate_analysis_reports(_analysis())

    modules = reports["modules.md"]
    relations = reports["relations.md"]
    paths = reports["main-paths.md"]
    assert "未发现的职责层" in modules
    assert "接入层 / 接入（1 个模块）" in modules
    assert "候选来源" in modules and "`src/app.py:4`" in modules
    assert "拆分复核" in modules and "职责单一" in modules
    assert "共 1 条已记录关系" in relations
    assert "请求入口 (`request`)" in relations
    assert "`src/app.py:11`：写入输出文件" in relations
    assert "请求入口 → 结果存储" in paths
    assert "复核轮次：2" in paths
    assert "模块 ID | 入边 | 出边" in paths


def test_analysis_reports_are_deterministic_for_same_analysis():
    analysis = _analysis()
    assert generate_analysis_reports(analysis) == generate_analysis_reports(analysis)


def test_legacy_flow_analysis_shape_is_supported():
    analysis = {
        "project": {"name": "旧格式链路"},
        "modules": [{"id": "a", "title": "接收请求", "evidence": [{"path": "app.py", "line": 1}]}],
        "relations": [],
        "mainPaths": [{"id": "p", "nodeIds": ["a"], "relationIds": [], "terminal": "a", "status": "complete"}],
    }
    reports = generate_analysis_reports(analysis)
    assert "旧格式链路" in reports["modules.md"]
    assert "接收请求" in reports["modules.md"]
    assert "成功路径" not in reports["main-paths.md"]


def test_modules_with_missing_or_unknown_layer_are_not_dropped():
    analysis = _analysis()
    analysis["stageB"]["modules"].append({
        "id": "orphan", "title": "未映射模块", "responsibility": "保留待归类职责",
        "layerId": "missing-layer", "evidence": [{"path": "src/orphan.py", "line": 1}],
    })
    report = generate_analysis_reports(analysis)["modules.md"]
    assert "## 未归类模块（1 个模块）" in report
    assert "未映射模块" in report
