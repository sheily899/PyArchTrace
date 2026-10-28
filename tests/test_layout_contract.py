from __future__ import annotations

from architecture_diagram.layout import layout_diagram, text_width
from architecture_diagram.models import validate_diagram
from architecture_diagram.quality import content_density_report, quality_report
from architecture_diagram.render import render_svg


def _evidence(path: str) -> list[dict]:
    return [{"path": path, "line": 1}]


def _graph(counts=(4, 4, 4), *, template="A", governance=0, groups=False):
    names = ["接入层", "编排层", "能力层", "数据层", "服务层", "扩展层", "运行层"]
    kinds = ["access", "orchestration", "capability", "data", "business", "other", "other"]
    layers = [{"id": f"L{i+1}", "name": names[i], "desc": "处理请求",
               "standardType": kinds[i], "evidence": _evidence(f"src/layer{i+1}.py")}
              for i in range(len(counts))]
    if governance:
        layers.append({"id": "G", "name": "治理与可靠性", "desc": "贯穿所有层",
                       "standardType": "governance", "crossCutting": True,
                       "evidence": _evidence("src/governance.py")})
    nodes = []
    for layer_index, count in enumerate(counts):
        for index in range(count):
            node_id = f"n{layer_index}_{index}"
            node = {"id": node_id, "layer": f"L{layer_index+1}",
                    "title": f"模块{layer_index+1}{index+1}", "desc": "处理业务请求",
                    "evidence": _evidence(f"src/{node_id}.py"), "order": index}
            if groups and count >= 11:
                node["group"] = ("入口" if index < count // 3 else "处理" if index < 2 * count // 3 else "输出")
            nodes.append(node)
    for index in range(governance):
        nodes.append({"id": f"g{index}", "layer": "G", "title": f"治理{index+1}",
                      "desc": "检查安全", "evidence": _evidence(f"src/g{index}.py")})
    offsets = [0]
    for count in counts[:-1]:
        offsets.append(offsets[-1] + count)
    main_chain = [nodes[offset]["id"] for offset in offsets[:7]]
    display_ids = [f"L{i+1}" for i in range(len(counts))]
    flows = [{"id": f"f{i}", "fromLayer": display_ids[i], "toLayer": display_ids[i+1],
              "label": "传递请求", "evidence": _evidence(f"src/flow{i}.py")}
             for i in range(len(display_ids) - 1)]
    graph = {"schemaVersion": 1, "id": "main", "title": "示例项目运行架构", "type": "architecture",
             "direction": "TB", "template": template, "mainChain": main_chain,
             "layerFlows": flows, "layers": layers, "nodes": nodes, "edges": [],
             "subDiagrams": [], "showEdgeLabels": False, "layout": {"contractVersion": 2}}
    return graph


def _assert_v2_geometry(graph):
    layout = layout_diagram(graph)
    geometry = quality_report(graph, layout)
    assert layout["width"] == 1440
    assert len({node["width"] for node in layout["nodes"]}) == 1
    assert not geometry["issues"], geometry["issues"]
    assert geometry["rowSymmetry"]["maxDifferencePx"] <= 1
    return layout


def test_contract_a_aligns_unequal_rows_and_uses_channel_centers():
    graph = _graph((4, 5, 4))
    layout = _assert_v2_geometry(graph)
    lanes = {lane["id"]: lane for lane in layout["layers"]}
    for edge in layout["edges"]:
        assert edge["layerFlow"] is True
        assert len(edge["points"]) == 2
        assert edge["points"][0]["x"] == lanes[edge["from"]]["x"] + lanes[edge["from"]]["width"] / 2
        assert edge["points"][1]["x"] == lanes[edge["to"]]["x"] + lanes[edge["to"]]["width"] / 2


def test_contract_a_rejects_module_edges_on_the_architecture_main_graph():
    graph = _graph()
    graph["edges"] = [{"id": "module-call", "from": "n0_0", "to": "n1_0",
                       "label": "直接模块调用", "kind": "call"}]
    report = quality_report(graph, layout_diagram(graph))

    assert report["passed"] is False
    assert any(issue["code"] == "module_edges_on_architecture_main" for issue in report["issues"])


def test_contract_a_rejects_edges_that_leave_reserved_channels_or_cross_layer_text():
    graph = _graph()
    layout = layout_diagram(graph)
    lanes = {lane["id"]: lane for lane in layout["layers"]}
    edge = layout["edges"][0]
    edge["to"] = "L3"
    edge["points"] = [
        {"x": lanes["L1"]["x"] + 18, "y": lanes["L1"]["y"] + lanes["L1"]["height"]},
        {"x": lanes["L1"]["x"] + 18, "y": lanes["L3"]["y"]},
    ]

    report = quality_report(graph, layout)
    issue_codes = {issue["code"] for issue in report["issues"]}

    assert report["passed"] is False
    assert "edge_outside_reserved_channel" in issue_codes
    assert "edge_through_layer_text" in issue_codes


def test_governance_is_a_separate_sidebar_and_is_not_a_runtime_lane():
    graph = _graph((4, 4, 4), governance=4)
    layout = _assert_v2_geometry(graph)
    side = next(layer for layer in layout["layers"] if layer.get("crossCutting"))
    assert side["crossCuttingLabel"] == "贯穿所有层"
    assert all(edge.get("from") != "G" and edge.get("to") != "G" for edge in layout["edges"])
    assert render_svg(graph, layout).count("贯穿所有层") == 1


def test_main_chain_modules_follow_numbered_order_within_each_lane():
    graph = _graph((4, 4, 4))
    graph["mainChain"] = ["n0_0", "n1_3", "n1_0", "n1_2", "n2_0"]
    layout = _assert_v2_geometry(graph)
    x_by_id = {node["id"]: node["x"] for node in layout["nodes"]}
    assert x_by_id["n1_3"] < x_by_id["n1_0"] < x_by_id["n1_2"] < x_by_id["n1_1"]
    positions = {node["id"]: node for node in layout["nodes"]}
    titles = {node["id"]: node["title"] for node in graph["nodes"]}
    for node_id in graph["mainChain"]:
        node = positions[node_id]
        title_left = node["x"] + (node["width"] - text_width(titles[node_id], 14)) / 2
        badge_right = node["x"] + 22
        assert title_left - badge_right >= 8


def test_twelve_node_layer_groups_without_shrinking_cards():
    graph = _graph((12, 4, 4), groups=True)
    layout = _assert_v2_geometry(graph)
    assert len(layout["groupFrames"]) == 3
    assert len(layout["nodes"]) == 20


def test_three_and_seven_layer_cases_are_supported_with_evidence_backed_merge():
    three = _graph((4, 4, 4))
    _assert_v2_geometry(three)
    seven = _graph((2, 2, 2, 2, 2, 2, 2))
    seven["layout"]["layerMerges"] = [{
        "id": "L34", "name": "能力与业务", "desc": "提供业务能力", "standardType": "other",
        "sourceLayerIds": ["L3", "L4"], "rationale": "相邻层在项目中共同承接业务能力",
        "evidence": _evidence("src/merge-evidence.py"),
    }]
    seven["layerFlows"] = [{"id": f"f{i}", "fromLayer": source, "toLayer": target,
                            "label": "请求流转", "evidence": _evidence(f"src/flow{i}.py")}
                           for i, (source, target) in enumerate([
                               ("L1", "L2"), ("L2", "L34"), ("L34", "L5"),
                               ("L5", "L6"), ("L6", "L7")])]
    _assert_v2_geometry(seven)
    invalid = _graph((2, 2, 2, 2, 2, 2, 2))
    assert any("相邻层合并方案" in error for error in validate_diagram(invalid))


def test_title_length_is_a_hard_validation_not_a_layout_wrap():
    graph = _graph()
    graph["nodes"][0]["title"] = "模块甲乙丙丁戊己庚辛"
    assert not any("超过 10 字" in error for error in validate_diagram(graph))
    graph["nodes"][0]["title"] = "模块甲乙丙丁戊己庚辛壬"
    assert any("超过 10 字" in error for error in validate_diagram(graph))


def test_long_descriptions_are_rejected_without_ellipsis():
    graph = _graph()
    graph["nodes"][0]["desc"] = "说明文字长度必须控制在十二个汉字以上"
    assert any("不超过 12 字" in error for error in validate_diagram(graph))


def test_template_b_places_offline_and_online_pipelines():
    graph = _graph((6, 6), template="B")
    offline = [node["id"] for node in graph["nodes"][:6]]
    online = [node["id"] for node in graph["nodes"][6:]]
    graph["layout"].update({
        "pipelineGroups": [
            {"id": "offline", "name": "离线知识构建", "nodeIds": offline, "evidence": _evidence("src/offline.py")},
            {"id": "online", "name": "在线请求处理", "nodeIds": online, "evidence": _evidence("src/online.py")},
        ],
        "pipelineMerge": {"id": "merge", "from": "offline", "to": "online", "label": "供在线检索",
                          "evidence": _evidence("src/merge.py")},
    })
    layout = _assert_v2_geometry(graph)
    assert layout["template"] == "B"
    assert [lane.get("pipeline") for lane in layout["layers"]] == ["offline", "online"]
    report = content_density_report(graph, layout)
    assert report["mainGraph"]["edgeCount"] == 1
    assert report["mainGraph"]["hardChecks"]["canvasWidthExactly1440px"] is True
    assert report["mainGraph"]["hardChecks"]["contrastAtLeast4_5To1"] is True


def test_template_b_reverse_flow_uses_exposed_lane_boundaries_and_flow_evidence():
    graph = _graph((6, 6), template="B")
    graph["layout"]["pipelineGroups"] = [
        {"id": "online", "name": "在线请求处理", "nodeIds": [node["id"] for node in graph["nodes"][6:]],
         "evidence": _evidence("src/online.py")},
        {"id": "offline", "name": "离线知识构建", "nodeIds": [node["id"] for node in graph["nodes"][:6]],
         "evidence": _evidence("src/offline.py")},
    ]
    graph["layout"].pop("pipelineMerge", None)
    graph["layerFlows"] = [{"id": "flow-back", "fromLayer": "online", "toLayer": "offline",
                            "label": "反馈", "evidence": _evidence("src/feedback.py")}]
    assert validate_diagram(graph) == []
    layout = _assert_v2_geometry(graph)
    flow = layout["edges"][0]
    by_id = {lane["id"]: lane for lane in layout["layers"]}
    assert flow["points"][0]["y"] == by_id["online"]["y"]
    assert flow["points"][-1]["y"] == by_id["offline"]["y"] + by_id["offline"]["height"]


def test_empty_layer_flow_label_is_not_a_phantom_collision_box_and_legend_is_rendered():
    graph = _graph((4, 4, 4))
    graph["layerFlows"][0]["label"] = ""
    layout = _assert_v2_geometry(graph)
    svg = render_svg(graph, layout)
    assert 'class="diagram-legend"' in svg
    assert "层间连接" in svg
    assert "主流向" not in svg
    assert svg.count('class="edge-label"') == 0
    assert sum(bool(edge.get("label")) for edge in layout["edges"]) == 1
    assert layout["legendFooterGap"] >= 45
    assert 'y="769"' in svg


def test_main_chain_badges_render_outside_cards_and_are_machine_audited():
    graph = _graph((4, 4, 4))
    layout = _assert_v2_geometry(graph)
    svg = render_svg(graph, layout)

    assert svg.count('class="chain-badge"') == len(graph["mainChain"])
    assert 'circle cx="0" cy="0" r="9"' in svg
    report = quality_report(graph, layout)
    assert report["counts"]["chain_badge_violations"] == 0
    assert report["counts"]["duplicate_layer_flow_label_violations"] == 0


def test_template_c_and_d_use_explicit_evidenced_groups():
    graph_c = _graph((12,), template="C", groups=True)
    members = [node["id"] for node in graph_c["nodes"]]
    graph_c["layout"]["kernelGroups"] = {
        "publicApi": {"name": "公共接口", "nodeIds": members[:3], "evidence": _evidence("src/api.py")},
        "kernel": {"name": "核心内核", "nodeIds": members[3:6], "evidence": _evidence("src/kernel.py")},
        "extensions": {"name": "适配扩展", "nodeIds": members[6:9], "evidence": _evidence("src/extensions.py")},
        "tooling": {"name": "开发工具", "nodeIds": members[9:], "evidence": _evidence("src/tools.py")},
    }
    layout_c = layout_diagram(graph_c)
    assert layout_c["template"] == "C"
    svg_c = render_svg(graph_c, layout_c)
    assert '#3B82F6' in svg_c and '#8B5CF6' in svg_c and '#64748B' in svg_c

    graph_d = _graph((4, 4, 4), template="D")
    members = [node["id"] for node in graph_d["nodes"]]
    graph_d["layout"]["deploymentZones"] = [
        {"id": "edge-zone", "name": "边缘区域", "nodeIds": members[:4], "evidence": _evidence("compose.yml")},
        {"id": "service-zone", "name": "服务区域", "nodeIds": members[4:8], "evidence": _evidence("compose.yml")},
        {"id": "data-zone", "name": "数据区域", "nodeIds": members[8:], "evidence": _evidence("compose.yml")},
    ]
    graph_d["layerFlows"] = [{"id": "zone1", "fromLayer": "edge-zone", "toLayer": "service-zone",
                               "label": "内网调用", "evidence": _evidence("compose.yml")},
                              {"id": "zone2", "fromLayer": "service-zone", "toLayer": "data-zone",
                               "label": "数据访问", "evidence": _evidence("compose.yml")}]
    assert layout_diagram(graph_d)["template"] == "D"


def test_more_than_twenty_five_modules_is_rejected_for_structure_aggregation():
    graph = _graph((10, 10, 10), groups=True)
    assert any("超过 25 个模块" in error for error in validate_diagram(graph))


def test_contract_a_allows_only_one_flow_per_adjacent_layer_pair():
    graph = _graph((4, 4, 4))
    graph["layerFlows"].append({"id": "duplicate", "fromLayer": "L1", "toLayer": "L2",
                                "label": "重复", "evidence": _evidence("src/duplicate.py")})

    import pytest
    with pytest.raises(ValueError, match="最多一条层间通道"):
        layout_diagram(graph)

