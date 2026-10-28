import pytest

from architecture_diagram.layout import layout_diagram
from architecture_diagram.models import validate_diagram
from architecture_diagram.quality import content_density_report


def _valid_sized_architecture():
    layers = [
        {"id": "L1", "name": "接入层", "standardType": "access", "evidence": [{"path": "src/1.py"}]},
        {"id": "L2", "name": "编排层", "standardType": "orchestration", "evidence": [{"path": "src/5.py"}]},
        {"id": "L3", "name": "数据层", "standardType": "data", "evidence": [{"path": "src/9.py"}]},
    ]
    nodes = [
        {"id": f"n{i}", "layer": f"L{(i - 1) // 4 + 1}", "title": f"模块{i}", "desc": "短说明", "evidence": [{"path": f"src/{i}.py"}]}
        for i in range(1, 13)
    ]
    return {"schemaVersion": 1, "id": "main", "title": "示例架构", "type": "architecture", "direction": "TB",
            "template": "A", "mainChain": ["n1", "n5", "n9"],
            "layerFlows": [
                {"id": "e1", "fromLayer": "L1", "toLayer": "L2", "label": "", "evidence": [{"path": "src/call.py"}]},
                {"id": "e2", "fromLayer": "L2", "toLayer": "L3", "label": "", "evidence": [{"path": "src/call.py"}]},
            ],
            "layout": {"contractVersion": 2}, "layers": layers, "nodes": nodes, "edges": [],
            "subDiagrams": [], "showEdgeLabels": False}


def test_content_density_report_accepts_clear_root_graph():
    diagram = _valid_sized_architecture()
    report = content_density_report(diagram, layout_diagram(diagram))
    assert report["passed"] is True
    assert report["mainGraph"]["moduleCount"] == 12
    assert report["mainGraph"]["edgeCount"] == 2
    assert all(item["withinTarget"] for item in report["mainGraph"]["layers"])
    assert report["mainGraph"]["hardChecks"]["mainModuleCountInRange"] is True
    assert report["mainGraph"]["hardChecks"]["mainEdgeCountAtMost8"] is True
    assert report["mainGraph"]["minimumBodyFontPx"] >= 12


def test_content_density_report_and_schema_reject_invalid_root_text_and_module_edges():
    diagram = _valid_sized_architecture()
    layout = layout_diagram(diagram)
    diagram["nodes"][0]["desc"] = "这是一个超过十二个汉字的模块说明"
    report = content_density_report(diagram, layout)
    assert "main_description_too_long" in {item["code"] for item in report["errors"]}
    diagram["edges"] = [{"id": "module-call", "from": "n1", "to": "n2", "label": "调用", "kind": "call"}]
    assert any("不能用模块级 edges" in error for error in validate_diagram(diagram))
    assert report["passed"] is False


def test_content_density_reports_soft_layer_target_without_blocking():
    diagram = _valid_sized_architecture()
    diagram["layers"].append({"id": "L4", "name": "扩展层", "standardType": "other", "evidence": [{"path": "src/extension.py"}]})
    diagram["nodes"][10]["layer"] = "L4"
    diagram["nodes"][11]["layer"] = "L4"
    report = content_density_report(diagram, layout_diagram(diagram))
    assert report["passed"] is True
    assert sum(item["code"] == "layer_below_target" and item["layer"] == "L4"
               for item in report["warnings"]) == 1


def test_governance_sidebar_is_excluded_from_per_layer_density_warnings():
    diagram = _valid_sized_architecture()
    diagram["layers"].append({"id": "G", "name": "治理与可靠性", "crossCutting": True,
                              "standardType": "governance", "evidence": [{"path": "src/guard.py"}]})
    diagram["nodes"].extend([
        {"id": "guard", "layer": "G", "title": "安全校验", "desc": "检查输出", "evidence": [{"path": "src/guard.py"}]},
        {"id": "audit", "layer": "G", "title": "操作审计", "desc": "记录操作", "evidence": [{"path": "src/audit.py"}]},
        {"id": "monitor", "layer": "G", "title": "运行监控", "desc": "记录状态", "evidence": [{"path": "src/monitor.py"}]},
        {"id": "redact", "layer": "G", "title": "敏感信息处理", "desc": "检查内容", "evidence": [{"path": "src/redact.py"}]},
        {"id": "retry", "layer": "G", "title": "调用重试", "desc": "恢复失败", "evidence": [{"path": "src/retry.py"}]},
        {"id": "audit-log", "layer": "G", "title": "审计记录", "desc": "记录事件", "evidence": [{"path": "src/audit_log.py"}]},
    ])
    report = content_density_report(diagram, layout_diagram(diagram))
    assert not any(item.get("layer") == "G" for item in report["warnings"])
    assert not any(item.get("layer") == "G" for item in report["errors"])
    governance = next(layer for layer in report["mainGraph"]["layers"] if layer["layerId"] == "G")
    assert governance["crossCutting"] is True
    assert governance["uniformSize"] is True
    assert report["mainGraph"]["hardChecks"]["atMostFiveNodesPerRow"] is True


def test_declared_empty_architecture_lane_is_rejected_before_layout():
    diagram = _valid_sized_architecture()
    diagram["layers"].append({"id": "empty", "name": "空层", "standardType": "other"})
    with pytest.raises(ValueError, match="没有模块"):
        layout_diagram(diagram)


def test_content_density_rejects_module_missing_from_layout():
    diagram = _valid_sized_architecture()
    layout = layout_diagram(diagram)
    layout["nodes"] = layout["nodes"][:-1]
    report = content_density_report(diagram, layout)
    assert report["passed"] is False
    assert report["mainGraph"]["hardChecks"]["nodeLayoutComplete"] is False
    assert any(item["code"] == "node_layout_missing" for item in report["errors"])


def test_drilldown_spacing_audit_respects_flow_columns_and_sequence_layout():
    parent = _valid_sized_architecture()
    flow = {
        "schemaVersion": 1, "id": "branch-flow", "title": "分支处理", "type": "flow", "direction": "LR",
        "layers": [{"id": "branch", "name": "并行分支"}, {"id": "merge", "name": "汇合"}],
        "nodes": [
            {"id": "a", "layer": "branch", "title": "分支一", "desc": "处理路径一", "evidence": [{"path": "src/a.py"}]},
            {"id": "b", "layer": "branch", "title": "分支二", "desc": "处理路径二", "evidence": [{"path": "src/b.py"}]},
            {"id": "c", "layer": "branch", "title": "分支三", "desc": "处理路径三", "evidence": [{"path": "src/c.py"}]},
            {"id": "d", "layer": "merge", "title": "结果汇合", "desc": "合并输出", "evidence": [{"path": "src/d.py"}]},
        ],
        "edges": [],
    }
    sequence = {
        "schemaVersion": 1, "id": "request-sequence", "title": "请求时序", "type": "sequence", "direction": "TB",
        "layers": [],
        "nodes": [
            {"id": name, "layer": "participants", "title": name, "desc": "时序参与方", "evidence": [{"path": f"src/{name}.py"}]}
            for name in ("入口", "处理器", "存储")
        ],
        "edges": [],
    }
    parent["subDiagrams"] = [flow, sequence]
    layouts = {
        flow["id"]: layout_diagram(flow, hardcoded_ports=True),
        sequence["id"]: layout_diagram(sequence),
    }

    report = content_density_report(parent, layout_diagram(parent), sub_layouts=layouts)

    assert report["passed"] is True
    assert not any(item["code"] in {"layer_spacing_mismatch", "layer_spacing_too_small", "layer_baseline_mismatch"}
                   for item in report["errors"])


def test_subdiagram_relationships_require_evidence_paths():
    diagram = _valid_sized_architecture()
    diagram["subDiagrams"] = [{
        "schemaVersion": 1, "id": "detail", "title": "处理细节", "type": "flow", "direction": "LR",
        "layers": [{"id": "A", "name": "输入"}, {"id": "B", "name": "处理"}],
        "nodes": [
            {"id": "input", "layer": "A", "title": "输入信息", "desc": "接收内容", "evidence": [{"path": "src/input.py"}]},
            {"id": "worker", "layer": "B", "title": "处理信息", "desc": "执行处理", "evidence": [{"path": "src/worker.py"}]},
        ],
        "edges": [{"id": "d1", "from": "input", "to": "worker", "label": "调用", "kind": "call"}],
    }]
    report = content_density_report(diagram, layout_diagram(diagram),
                                    sub_layouts={"detail": layout_diagram(diagram["subDiagrams"][0], hardcoded_ports=True)})
    assert report["passed"] is False
    assert any(item["code"] == "edge_evidence_missing" and item["graph"] == "detail" for item in report["errors"])


def test_architecture_root_rejects_module_level_reverse_calls():
    diagram = _valid_sized_architecture()
    diagram["edges"] = [{"id": "reverse-call", "from": "n5", "to": "n1", "label": "调用", "kind": "call"}]
    errors = validate_diagram(diagram)
    assert any("不能用模块级 edges" in error for error in errors)


def test_architecture_drilldown_lanes_have_uniform_node_dimensions():
    child = {
        "schemaVersion": 1, "id": "uniform-child", "title": "分支处理", "type": "flow", "direction": "TB",
        "layers": [{"id": "parallel", "name": "并行处理"}, {"id": "merge", "name": "合并"}],
        "nodes": [
            {"id": "a", "layer": "parallel", "title": "关键词判断", "desc": "检查固定规则"},
            {"id": "b", "layer": "parallel", "title": "语义向量召回", "desc": "计算相似度并返回候选结果"},
            {"id": "c", "layer": "merge", "title": "融合结果", "desc": "选择最终类别"},
        ],
        "edges": [],
    }
    layout = layout_diagram(child, hardcoded_ports=True)
    dimensions_by_layer = {}
    for node in layout["nodes"]:
        dimensions_by_layer.setdefault(node["layer"], set()).add((node["width"], node["height"]))
    assert all(len(dimensions) == 1 for dimensions in dimensions_by_layer.values())
