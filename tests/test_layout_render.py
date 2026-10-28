import copy
import re

from architecture_diagram.layout import layout_diagram
from architecture_diagram.render import render_svg, render_html
from architecture_diagram.quality import quality_report


def test_architecture_nodes_share_layer_baseline_and_do_not_overlap(simple_diagram):
    layout = layout_diagram(simple_diagram)
    positions = layout["nodes"]
    by_id = {item["id"]: item for item in positions}
    assert by_id["web"]["y"] != by_id["router"]["y"]
    assert by_id["router"]["y"] != by_id["store"]["y"]
    assert all(item["width"] >= 194 and 52 <= item["height"] <= 68 for item in positions)
    report = quality_report(simple_diagram, layout)
    assert report["counts"]["label_overlaps"] == 0
    assert report["counts"]["architecture_card_height_errors"] == 0
    assert report["counts"]["directional_port_errors"] == 0
    assert report["counts"]["port_outset_errors"] == 0


def test_v2_architecture_refuses_legacy_module_routes(simple_diagram):
    from architecture_diagram.render import render_svg
    import pytest

    legacy = copy.deepcopy(simple_diagram)
    legacy.pop("layout")
    layout = layout_diagram(simple_diagram)
    with pytest.raises(ValueError, match="V2"):
        layout_diagram(legacy)
    legacy_layout = dict(layout, contractVersion=1)
    with pytest.raises(ValueError, match="V2"):
        render_svg(legacy, legacy_layout)
    lanes = {item["id"]: item for item in layout["layers"]}
    for edge in layout["edges"]:
        source, target = lanes[edge["from"]], lanes[edge["to"]]
        points = edge["points"]
        assert edge["layerFlow"] is True
        assert points[0] == {"x": source["x"] + source["width"] / 2, "y": source["y"] + source["height"]}
        assert points[-1] == {"x": target["x"] + target["width"] / 2, "y": target["y"]}


def test_architecture_wraps_layers_after_five_modules_without_expanding_canvas():
    graph = {
        "schemaVersion": 1, "id": "wrapped", "title": "分行布局", "type": "architecture", "direction": "TB",
        "template": "A", "mainChain": ["n0", "n1"], "layerFlows": [],
        "layout": {"contractVersion": 2},
        "layers": [{"id": "L1", "name": "能力层", "standardType": "capability"}],
        "nodes": [{"id": f"n{i}", "layer": "L1", "title": f"能力模块{i}", "desc": "处理业务"} for i in range(6)],
        "edges": [],
    }
    layout = layout_diagram(graph)
    positions = layout["nodes"]
    assert len({item["row"] for item in positions}) == 2
    assert max(sum(item["row"] == row for item in positions) for row in {item["row"] for item in positions}) == 3
    assert len({(item["width"], item["height"]) for item in positions}) == 1
    assert layout["width"] <= 1440
    assert quality_report(graph, layout)["counts"]["node_overlaps"] == 0


def test_architecture_routes_use_side_ports_and_fixed_outward_stubs():
    graph = {
        "schemaVersion": 1, "id": "hardcoded-ports", "title": "端口路由", "type": "architecture", "direction": "TB",
        "layers": [{"id": "L1", "name": "编排层"}, {"id": "L2", "name": "能力层"}],
        "nodes": [
            {"id": "source", "layer": "L1", "title": "主处理", "desc": "发起能力调用", "column": 0, "position": {"x": 48, "y": 130}},
            {"id": "peer", "layer": "L1", "title": "辅助处理", "desc": "并行辅助", "column": 2, "position": {"x": 360, "y": 130}},
            {"id": "target", "layer": "L2", "title": "目标能力", "desc": "接收调用", "column": 1},
        ],
        "edges": [
            {"id": "side", "from": "source", "to": "peer", "label": "同层调用", "kind": "call"},
            {"id": "vertical", "from": "source", "to": "target", "label": "跨层调用", "kind": "call"},
        ],
    }
    import pytest
    with pytest.raises(ValueError, match="layout.contractVersion=2"):
        layout_diagram(graph)


def test_architecture_swimlanes_use_compact_spacing(simple_diagram):
    layout = layout_diagram(simple_diagram)
    lanes = {lane["id"]: lane for lane in layout["layers"] if not lane.get("crossCutting")}
    ordered = [lanes[layer["id"]] for layer in simple_diagram["layers"]]
    assert all(lane["height"] <= 160 for lane in ordered)
    assert all(right["y"] - (left["y"] + left["height"]) == 36
               for left, right in zip(ordered, ordered[1:]))


def test_architecture_column_hints_align_evidenced_flows_without_crossing_cards():
    graph = {
        "schemaVersion": 1, "id": "column-alignment", "title": "分层主流向", "type": "architecture", "direction": "TB",
        "template": "A", "mainChain": ["entry", "orchestrator", "worker", "memory"],
        "layout": {"contractVersion": 2}, "showEdgeLabels": False,
        "layers": [{"id": "access", "name": "接入层", "standardType": "access"},
                   {"id": "orchestration", "name": "编排层", "standardType": "orchestration"},
                   {"id": "data", "name": "数据层", "standardType": "data"}],
        "nodes": [{"id": "entry", "layer": "access", "title": "用户入口", "desc": "接收请求"},
                  {"id": "access-peer", "layer": "access", "title": "网页入口", "desc": "显示结果"},
                  {"id": "orchestrator", "layer": "orchestration", "title": "流程调度", "desc": "推进任务"},
                  {"id": "worker", "layer": "orchestration", "title": "工具处理", "desc": "选择工具"},
                  {"id": "memory", "layer": "data", "title": "任务记录", "desc": "保存状态"}],
        "layerFlows": [{"id": "f1", "fromLayer": "access", "toLayer": "orchestration", "label": "请求流转"},
                       {"id": "f2", "fromLayer": "orchestration", "toLayer": "data", "label": "结果保存"}],
        "edges": [], "subDiagrams": [],
    }
    layout = layout_diagram(graph)
    report = quality_report(graph, layout)
    positions = {node["id"]: node for node in layout["nodes"]}

    lanes = {layer["id"]: layer for layer in layout["layers"]}
    assert all(edge["points"][0]["x"] == lanes[edge["from"]]["x"] + lanes[edge["from"]]["width"] / 2
               for edge in layout["edges"])
    assert layout["width"] <= 1440
    assert report["passed"] is True


def test_cross_cutting_sidebar_fits_when_diagram_has_only_one_regular_lane():
    graph = {
        "schemaVersion": 1, "id": "single-lane-cross-cutting", "title": "单层治理关系",
        "type": "architecture", "direction": "TB", "template": "A",
        "mainChain": ["worker"], "layerFlows": [], "layout": {"contractVersion": 2},
        "layers": [
            {"id": "capability", "name": "能力层", "standardType": "capability"},
            {"id": "governance", "name": "治理层", "standardType": "governance", "crossCutting": True},
        ],
        "nodes": [
            {"id": "worker", "layer": "capability", "title": "处理能力", "desc": "执行工作"},
            {"id": "guard", "layer": "governance", "title": "安全检查", "desc": "检查结果"},
        ],
        "edges": [],
    }
    layout = layout_diagram(graph)
    report = quality_report(graph, layout)
    assert layout["layers"][-1]["y"] + layout["layers"][-1]["height"] <= layout["height"]
    assert report["counts"]["canvas_overflows"] == 0


def test_nested_architecture_flow_uses_fixed_directional_ports_and_visible_return():
    graph = {
        "schemaVersion": 1, "id": "nested-flow", "title": "分支处理细节", "type": "flow", "direction": "LR",
        "layers": [{"id": "input", "name": "输入"}, {"id": "branches", "name": "处理分支"}],
        "nodes": [
            {"id": "input", "layer": "input", "title": "订单请求", "desc": "识别订单问题"},
            {"id": "lookup", "layer": "branches", "title": "查询订单", "desc": "读取本地演示数据", "order": 1},
            {"id": "draft", "layer": "branches", "title": "生成工单草稿", "desc": "创建待审核记录", "order": 2},
        ],
        "edges": [
            {"id": "lookup-edge", "from": "input", "to": "lookup", "label": "订单查询", "kind": "call"},
            {"id": "draft-edge", "from": "input", "to": "draft", "label": "工单草稿", "kind": "call"},
        ],
    }
    layout = layout_diagram(graph, backend="elkjs", hardcoded_ports=True)
    nodes = {node["id"]: node for node in layout["nodes"]}
    group = next(item for item in layout["edgeGroups"] if item["pattern"] == "fan_out")
    assert group["trunkPoints"][0] == {
        "x": nodes["input"]["x"] + nodes["input"]["width"],
        "y": nodes["input"]["y"] + nodes["input"]["height"] / 2,
    }
    for edge in layout["edges"]:
        target = nodes[edge["to"]]
        points = group["branchPoints"][edge["id"]]
        assert points[0]["x"] == group["busX"]
        assert points[-1] == {"x": target["x"], "y": target["y"] + target["height"] / 2}
        assert all(a["y"] == b["y"] for a, b in zip(points, points[1:]))
        assert edge["bends"] == 0
    report = quality_report(graph, layout, hardcoded_ports=True)
    assert report["passed"]
    assert report["counts"]["directional_port_errors"] == 0
    html = render_html(graph, layout, architecture_detail=True)
    assert 'id="back"' in html and "返回上一级" in html
    assert '"hardcodedPorts":true' in html
    assert 'data-route-mode="hardcoded-detail"' in html


def test_nested_tb_flow_uses_top_and_bottom_ports():
    graph = {
        "schemaVersion": 1, "id": "nested-tb", "title": "纵向处理细节", "type": "flow", "direction": "TB",
        "layers": [{"id": "input", "name": "输入"}, {"id": "output", "name": "输出"}],
        "nodes": [
            {"id": "input", "layer": "input", "title": "意图结果", "desc": "待业务处理"},
            {"id": "output", "layer": "output", "title": "结构化结果", "desc": "返回调用方"},
        ],
        "edges": [{"id": "down", "from": "input", "to": "output", "label": "处理结果", "kind": "call"}],
    }
    layout = layout_diagram(graph, hardcoded_ports=True)
    edge = layout["edges"][0]
    nodes = {node["id"]: node for node in layout["nodes"]}
    source, target = nodes["input"], nodes["output"]
    assert edge["points"][0] == {"x": source["x"] + source["width"] / 2,
                                 "y": source["y"] + source["height"]}
    assert edge["points"][-1] == {"x": target["x"] + target["width"] / 2, "y": target["y"]}
    assert quality_report(graph, layout, hardcoded_ports=True)["passed"]


def test_main_route_fan_out_does_not_stack_peer_nodes():
    graph = {
        "schemaVersion": 1, "id": "fanout", "title": "请求分发", "type": "flow", "direction": "TB",
        "layers": [{"id": "L1", "name": "编排层"}, {"id": "L2", "name": "能力层"}],
        "nodes": [
            {"id": "router", "layer": "L1", "title": "请求分发", "desc": "选择处理分支"},
            {"id": "consult", "layer": "L2", "title": "咨询处理", "desc": "处理产品问题", "order": 1},
            {"id": "orders", "layer": "L2", "title": "订单处理", "desc": "处理订单问题", "order": 2},
            {"id": "aftersales", "layer": "L2", "title": "售后处理", "desc": "处理售后问题", "order": 3},
        ],
        "edges": [
            {"id": "to-consult", "from": "router", "to": "consult", "label": "咨询分支", "kind": "call", "main": True},
            {"id": "to-orders", "from": "router", "to": "orders", "label": "订单分支", "kind": "call", "main": True},
            {"id": "to-aftersales", "from": "router", "to": "aftersales", "label": "售后分支", "kind": "call", "main": True},
        ],
    }
    layout = layout_diagram(graph, backend="builtin", hardcoded_ports=True)
    positions = {node["id"]: node for node in layout["nodes"]}
    peers = [positions[node_id] for node_id in ("consult", "orders", "aftersales")]
    assert len({node["x"] for node in peers}) == len(peers)
    assert quality_report(graph, layout, hardcoded_ports=True)["counts"]["node_overlaps"] == 0
    assert quality_report(graph, layout, hardcoded_ports=True)["counts"]["label_overlaps"] == 0


def test_flow_viewport_contains_full_width_of_horizontal_swimlanes():
    graph = {
        "schemaVersion": 1, "id": "tb-lane-bounds", "title": "意图评分汇合", "type": "flow", "direction": "TB",
        "layers": [{"id": "signals", "name": "并行识别结果"}, {"id": "fusion", "name": "分数融合"}],
        "nodes": [
            {"id": "model", "layer": "signals", "title": "语言模型语义分类", "desc": "返回意图与置信度"},
            {"id": "vector", "layer": "signals", "title": "向量样例相似度", "desc": "比较意图样例向量"},
            {"id": "merge", "layer": "fusion", "title": "规则与模型分数融合", "desc": "排序并处理低置信度回退"},
        ],
        "edges": [],
    }
    layout = layout_diagram(graph, backend="builtin")
    assert all(layer["x"] + layer["width"] <= layout["width"] for layer in layout["layers"])
    assert quality_report(graph, layout)["counts"]["canvas_overflows"] == 0


def test_architecture_layer_flows_are_centered_independently_of_card_columns(simple_diagram):
    layout = layout_diagram(simple_diagram)
    lanes = {layer["id"]: layer for layer in layout["layers"]}
    assert len(layout["edges"]) == len(simple_diagram["layerFlows"])
    for edge in layout["edges"]:
        assert edge["points"][0]["x"] == lanes[edge["from"]]["x"] + lanes[edge["from"]]["width"] / 2
        assert edge["points"][-1]["x"] == lanes[edge["to"]]["x"] + lanes[edge["to"]]["width"] / 2
    assert quality_report(simple_diagram, layout)["counts"]["node_overlaps"] == 0


def test_architecture_html_reuses_the_supplied_root_layout(simple_diagram):
    layout = layout_diagram(simple_diagram)
    svg = render_svg(simple_diagram, layout)
    html = render_html(simple_diagram, layout)

    assert f'<div id="canvas">{svg}</div>' in html
    assert "主流向" not in svg
    assert "主流向" not in html
    assert 'graph.edges.some(edge=>!edge.layerFlow)' in html
    assert 'const points=hardcodedPorts' in html


def test_non_architecture_arrowheads_are_compact_solid_triangles_matching_line_color():
    import xml.etree.ElementTree as ET

    graph = {
        "schemaVersion": 1, "id": "arrow-colors", "title": "调用关系", "type": "flow", "direction": "LR",
        "layers": [{"id": "a", "name": "输入"}, {"id": "b", "name": "处理"}],
        "nodes": [{"id": "source", "layer": "a", "title": "消息入口", "desc": "接收消息"},
                  {"id": "target", "layer": "b", "title": "异步处理", "desc": "登记任务"}],
        "edges": [{"id": "async", "from": "source", "to": "target", "label": "登记任务", "kind": "call", "async": True}],
    }
    svg = render_svg(graph, layout_diagram(graph, backend="builtin"))
    root = ET.fromstring(svg)
    ns = {"svg": "http://www.w3.org/2000/svg"}
    markers = {marker.attrib["id"]: marker for marker in root.findall(".//svg:marker", ns)}
    assert markers
    for marker in markers.values():
        assert marker.attrib["markerUnits"] == "userSpaceOnUse"
        assert marker.attrib["viewBox"] == "0 0 12 10"
        assert marker.attrib["markerWidth"] == "12" and marker.attrib["markerHeight"] == "10"
        assert marker.attrib["refX"] == "0"
        arrow_shape = marker.find("svg:path", ns)
        assert arrow_shape.attrib["d"] == "M 0 0 L 12 5 L 0 10 Z"
    for path in root.findall(".//svg:path[@marker-end]", ns):
        marker_id = path.attrib["marker-end"].removeprefix("url(#").removesuffix(")")
        marker = markers[marker_id]
        assert marker.find("svg:path", ns).attrib["fill"].lower() == path.attrib["stroke"].lower()
        assert path.attrib["stroke-width"] == "1.8"
        assert path.attrib["stroke-linecap"] == "butt"
        coords = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", path.attrib["d"])]
        assert abs(coords[-2] - float(path.attrib["data-arrow-shaft-x"])) < 0.11
        assert abs(coords[-1] - float(path.attrib["data-arrow-shaft-y"])) < 0.11
        tip_delta = ((float(path.attrib["data-arrow-tip-x"]) - coords[-2]) ** 2
                     + (float(path.attrib["data-arrow-tip-y"]) - coords[-1]) ** 2) ** 0.5
        assert abs(tip_delta - 12) < 0.11


def test_architecture_layer_flows_use_large_blue_arrowheads(simple_diagram):
    import xml.etree.ElementTree as ET

    layout = layout_diagram(simple_diagram)
    root = ET.fromstring(render_svg(simple_diagram, layout))
    ns = {"svg": "http://www.w3.org/2000/svg"}
    markers = {marker.attrib["id"]: marker for marker in root.findall(".//svg:marker", ns)}
    marker = markers["arrow-main-155EEF"]
    assert marker.attrib["markerUnits"] == "userSpaceOnUse"
    assert marker.attrib["viewBox"] == "0 0 18 14"
    assert marker.attrib["markerWidth"] == "18" and marker.attrib["markerHeight"] == "14"
    assert marker.attrib["refX"] == "0"
    assert marker.find("svg:path", ns).attrib["d"] == "M 0 0 L 18 7 L 0 14 Z"
    flows = root.findall(".//svg:g[@data-layer-flow='true']/svg:path[@class='edge-line']", ns)
    assert len(flows) == 2
    assert all(path.attrib["stroke-width"] == "3.6" for path in flows)
    assert all(path.attrib["stroke-linecap"] == "butt" for path in flows)
    assert all(path.attrib["marker-end"] == "url(#arrow-main-155EEF)" for path in flows)
    for path in flows:
        coords = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", path.attrib["d"])]
        tip_delta = ((float(path.attrib["data-arrow-tip-x"]) - coords[-2]) ** 2
                     + (float(path.attrib["data-arrow-tip-y"]) - coords[-1]) ** 2) ** 0.5
        assert abs(tip_delta - 18) < 0.11
    legend = root.find(".//svg:path[@data-marker-size='main']", ns)
    assert legend is not None and legend.attrib["marker-end"] == "url(#arrow-main-155EEF)"
    assert legend.attrib["stroke-linecap"] == "butt"
    assert float(legend.attrib["data-arrow-tip-x"]) - float(legend.attrib["data-arrow-shaft-x"]) == 18


def test_interactive_svg_rebuild_stops_arrow_shafts_at_head_bases():
    graph = {
        "schemaVersion": 1, "id": "interactive-arrow", "title": "调用链路", "type": "flow", "direction": "LR",
        "layers": [{"id": "input", "name": "入口"}, {"id": "service", "name": "服务"}],
        "nodes": [{"id": "request", "layer": "input", "title": "请求入口", "desc": "接收请求"},
                  {"id": "handler", "layer": "service", "title": "请求处理", "desc": "执行业务"}],
        "edges": [{"id": "request-handler", "from": "request", "to": "handler", "label": "调用", "kind": "call"}],
    }
    html = render_html(graph, layout_diagram(graph, backend="builtin"))
    assert 'refX="0"' in html
    assert "clientArrowShaftPoints" in html
    assert "setClientArrowPath" in html
    assert 'stroke-linecap="butt"${dash}' in html
    assert "stroke-linejoin:round;stroke-linecap:butt" in html


def test_governance_edges_bind_modules_and_render_directed_dashed_arrows():
    graph = {
        "schemaVersion": 1, "id": "governance-edge", "title": "治理关系", "type": "flow", "direction": "LR",
        "layers": [{"id": "runtime", "name": "运行模块"}, {"id": "guard", "name": "治理能力"}],
        "nodes": [{"id": "request", "layer": "runtime", "title": "请求入口", "desc": "接收业务请求"},
                  {"id": "permission", "layer": "guard", "title": "权限校验", "desc": "检查访问范围"}],
        "edges": [{"id": "permission-check", "from": "request", "to": "permission",
                   "label": "校验权限", "kind": "governance"}],
    }
    layout = layout_diagram(graph, backend="builtin", hardcoded_ports=True)
    svg = render_svg(graph, layout)
    edge = layout["edges"][0]
    source = next(node for node in layout["nodes"] if node["id"] == "request")
    target = next(node for node in layout["nodes"] if node["id"] == "permission")
    assert edge["points"][0] == {"x": source["x"] + source["width"],
                                  "y": source["y"] + source["height"] / 2}
    assert edge["points"][-1] == {"x": target["x"], "y": target["y"] + target["height"] / 2}
    assert 'data-kind="governance"' in svg
    assert 'stroke-dasharray="5 5"' in svg
    assert 'marker-end="url(#arrow-D4A24C)"' in svg
    assert quality_report(graph, layout, hardcoded_ports=True)["passed"] is True
    html = render_html(graph, layout, architecture_detail=True)
    assert "edge.kind==='governance'||" not in html
    assert "gov?'':` marker-end" not in html
    assert "function updateGroupedEdges(boxes)" in html
    assert "updateGroupedEdges(boxes);" in html
    assert "if(edge.kind==='governance')continue;" not in html


def test_governance_fan_in_keeps_dashed_bus_and_single_matching_arrowhead():
    import xml.etree.ElementTree as ET

    graph = {
        "schemaVersion": 1, "id": "governance-fan-in", "title": "治理约束汇入", "type": "flow", "direction": "TB",
        "layers": [{"id": "runtime", "name": "运行模块"}, {"id": "guard", "name": "治理能力"}],
        "nodes": [
            {"id": "chat", "layer": "runtime", "title": "消息接入", "desc": "接收客户消息"},
            {"id": "router", "layer": "runtime", "title": "智能体调度", "desc": "分配处理能力"},
            {"id": "ticket", "layer": "runtime", "title": "工单服务", "desc": "保存工单信息"},
            {"id": "guard", "layer": "guard", "title": "回复安全守卫", "desc": "检查输出内容"},
        ],
        "edges": [
            {"id": "g-chat", "from": "chat", "to": "guard", "label": "检查消息", "kind": "governance"},
            {"id": "g-router", "from": "router", "to": "guard", "label": "检查调度", "kind": "governance"},
            {"id": "g-ticket", "from": "ticket", "to": "guard", "label": "检查工单", "kind": "governance"},
        ],
    }
    layout = layout_diagram(graph, backend="builtin", hardcoded_ports=True)
    group = layout["edgeGroups"][0]
    assert group["pattern"] == "fan_in" and group["kind"] == "governance"

    root = ET.fromstring(render_svg(graph, layout))
    ns = {"svg": "http://www.w3.org/2000/svg"}
    bus = root.find(".//svg:path[@class='edge-group-line']", ns)
    assert bus is not None
    assert bus.attrib["stroke"].lower() == "#d4a24c"
    assert bus.attrib["stroke-dasharray"] == "5 5"
    branch_edges = [root.find(f".//svg:g[@data-edge='{edge_id}']", ns) for edge_id in group["edgeIds"]]
    assert all(edge is not None and edge.attrib["data-show-marker"] == "false" for edge in branch_edges)
    assert all(edge.find("svg:path[@class='edge-line']", ns).get("marker-end") is None for edge in branch_edges)

    group_arrow = root.find(f".//svg:g[@data-edge-group-arrow='{group['id']}']", ns)
    assert group_arrow is not None
    arrow_line = group_arrow.find("svg:path[@class='edge-line']", ns)
    assert arrow_line is not None
    assert arrow_line.attrib["stroke"].lower() == "#d4a24c"
    assert arrow_line.attrib["stroke-dasharray"] == "5 5"
    assert arrow_line.attrib["marker-end"] == "url(#arrow-D4A24C)"
    assert quality_report(graph, layout, hardcoded_ports=True)["passed"] is True


def test_svg_uses_chinese_visible_labels_and_orthogonal_edges(simple_diagram):
    layout = layout_diagram(simple_diagram)
    svg = render_svg(simple_diagram, layout)
    assert "消息入口" in svg and "意图分流" in svg
    assert "IntentRecognizer" not in svg
    assert "<marker" in svg
    assert 'id="arrow-main-155EEF"' in svg and 'orient="auto"' in svg
    assert 'marker-end="url(#arrow-main-155EEF)"' in svg
    assert 'markerUnits="userSpaceOnUse"' in svg
    assert 'markerWidth="18" markerHeight="14"' in svg
    assert "#F8FAFC" in svg
    assert 'class="status"' not in svg
    assert "已接入" not in svg and "部分接入" not in svg
    assert all(color in svg for color in ("#EFF6FF", "#3B82F6", "#FFFBEB", "#F59E0B", "#ECFEFF", "#06B6D4"))
    assert 'class="node compact"' in svg


def test_architecture_flow_detail_legend_explains_every_rendered_line_style():
    graph = {
        "schemaVersion": 1, "id": "legend-flow", "title": "异步与数据访问", "type": "flow", "direction": "LR",
        "layers": [{"id": "in", "name": "输入"}, {"id": "work", "name": "处理"},
                   {"id": "out", "name": "存储"}],
        "nodes": [
            {"id": "a", "layer": "in", "title": "请求入口", "desc": "接收消息"},
            {"id": "b", "layer": "work", "title": "异步处理", "desc": "登记后台任务"},
            {"id": "c", "layer": "out", "title": "工单记录", "desc": "保存处理结果"},
        ],
        "edges": [
            {"id": "async", "from": "a", "to": "b", "label": "异步登记", "kind": "call", "async": True},
            {"id": "write", "from": "b", "to": "c", "label": "写入工单", "kind": "db_write"},
        ],
    }
    layout = layout_diagram(graph, backend="builtin", hardcoded_ports=True)
    svg = render_svg(graph, layout)

    assert 'data-legend-key="async"' in svg and "异步调用" in svg
    assert 'data-legend-key="data"' in svg and "数据访问" in svg
    assert layout["height"] >= max(node["y"] + node["height"] for node in layout["nodes"]) + 42


def test_architecture_flow_detail_keeps_full_titles_and_wraps_full_descriptions():
    graph = {
        "schemaVersion": 1, "id": "full-copy", "title": "完整文字", "type": "flow", "direction": "LR",
        "layers": [{"id": "in", "name": "输入"}, {"id": "out", "name": "结果"}],
        "nodes": [
            {"id": "source", "layer": "in", "title": "智能体工具白名单与提示词注入",
             "desc": "订单查询、字段建议与草稿生成"},
            {"id": "target", "layer": "out", "title": "本地工单草稿与确认",
             "desc": "生成草稿并由客服编辑后提交审核"},
        ],
        "edges": [],
    }
    layout = layout_diagram(graph, backend="builtin", hardcoded_ports=True)
    positions = {item["id"]: item for item in layout["nodes"]}
    svg = render_svg(graph, layout)

    for node in graph["nodes"]:
        position = positions[node["id"]]
        assert position["title_lines"] == [node["title"]]
        assert "".join(position["desc_lines"]) == node["desc"]
        assert 58 <= position["height"] <= 68
        assert "…" not in svg


def test_sequence_detail_legend_explains_async_messages_and_lifelines():
    graph = {
        "schemaVersion": 1, "id": "legend-sequence", "title": "请求时序", "type": "sequence", "direction": "TB",
        "layers": [],
        "nodes": [
            {"id": "client", "layer": "sequence", "title": "客户端", "desc": "提交请求"},
            {"id": "service", "layer": "sequence", "title": "业务服务", "desc": "处理请求"},
        ],
        "edges": [
            {"id": "request", "from": "client", "to": "service", "label": "提交请求", "kind": "http", "main": True},
            {"id": "task", "from": "service", "to": "client", "label": "异步回执", "kind": "event", "async": True},
        ],
    }
    layout = layout_diagram(graph)
    svg = render_svg(graph, layout)

    assert 'data-legend-key="main"' in svg and "主链路" in svg
    assert 'data-legend-key="async"' in svg and "异步调用" in svg
    assert 'data-legend-key="lifeline"' in svg and "参与者生命线" in svg
    lifeline_end = layout["height"] - 52
    assert f'L {layout["lifelines"]["client"]:.1f} {lifeline_end}' in svg
    assert lifeline_end < layout["height"] - 27


def test_architecture_html_keeps_readonly_details_and_drilldown_without_status(simple_diagram):
    diagram = copy.deepcopy(simple_diagram)
    diagram["nodes"][1]["drilldown"] = "intent-detail"
    diagram["nodes"][1]["details"] = {
        "summary": "分配处理路径", "responsibilities": ["选择处理分支"], "inputs": ["用户诉求"],
        "outputs": ["处理模块"], "depends_on": ["knowledge"], "used_by": ["chat"],
        "key_files": ["src/router.py"], "tech": ["asyncio"],
        "confidence": {"evidence": ["src/router.py:8"], "inference": [], "pending": []},
    }
    diagram["subDiagrams"] = [{
        "schemaVersion": 1, "id": "intent-detail", "title": "意图识别细节", "type": "flow", "direction": "LR",
        "layers": [{"id": "I1", "name": "输入"}, {"id": "I2", "name": "处理"}],
        "nodes": [{"id": "input", "layer": "I1", "title": "用户诉求", "desc": "待识别内容"},
                  {"id": "match", "layer": "I2", "title": "关键词匹配", "desc": "查找规则命中"}],
        "edges": [{"id": "ie1", "from": "input", "to": "match", "label": "匹配规则", "kind": "call"}],
        "subDiagrams": [],
    }]
    html = render_html(diagram)
    assert 'class="status"' not in html
    assert "已接入" not in html and "部分接入" not in html
    assert "实现情况" not in html
    assert "drill-icon" in html and "细看" not in html and 'id="back"' in html
    assert 'id="module-details"' in html and "依赖模块" in html and "src/router.py" in html
    assert "意图识别细节" in html and "关键词匹配" in html
    assert 'id="details"' not in html and 'id="openChild"' not in html


def test_svg_drilldown_uses_icon_without_visible_text(simple_diagram):
    diagram = copy.deepcopy(simple_diagram)
    diagram["nodes"][1]["drilldown"] = "intent-detail"
    svg = render_svg(diagram, layout_diagram(diagram))

    assert 'class="drill-icon"' in svg
    assert 'aria-label="进入下钻图"' in svg
    assert "细看" not in svg

    exported = render_svg(diagram, layout_diagram(diagram), include_drilldown=False)
    assert 'class="drill-icon"' not in exported

    html = render_html(diagram, layout_diagram(diagram))
    assert 'class="drill-icon"' in html
    assert "currentId===payload.root" in html and "clone.querySelectorAll('.drill-icon')" in html


def test_html_embeds_editable_json_and_no_remote_assets(simple_diagram):
    layout = layout_diagram(simple_diagram)
    html = render_html(simple_diagram, layout)
    assert "导出矢量图" in html
    assert "导出高清图片" in html
    assert "重置布局" in html
    assert 'id="exportSvg"' in html and 'id="exportPng"' in html and 'id="reset"' in html
    assert 'id="back"' in html
    for control in ("addNode", "addEdge", "deleteNode", "setDrilldown", "importJson", "exportJson", "details", "zoomIn", "zoomOut", "openChild"):
        assert f'id="{control}"' not in html
    assert "dblclick" not in html
    assert '<script src=' not in html and '<link href=' not in html


def test_sequence_layout_orders_messages_by_time(simple_diagram):
    sequence = {
        **simple_diagram,
        "type": "sequence",
        "layers": [],
        "nodes": [
            {"id": "user", "title": "用户", "desc": "", "status": "implemented"},
            {"id": "service", "title": "处理服务", "desc": "", "status": "implemented"},
        ],
        "edges": [
            {"id": "late", "from": "user", "to": "service", "label": "处理结果", "kind": "call", "order": 2},
            {"id": "early", "from": "service", "to": "user", "label": "处理请求", "kind": "call", "order": 1},
        ],
    }
    layout = layout_diagram(sequence)
    assert [item["id"] for item in layout["edges"]] == ["early", "late"]
    assert all(node["x"] >= 0 and node["x"] + node["width"] <= layout["width"] for node in layout["nodes"])
    svg = render_svg(sequence, layout)
    assert 'class="architecture-diagram"' not in svg
    assert 'class="node compact"' not in svg
    assert 'marker-end="url(#arrow-94A3B8)"' in svg
    html = render_html(sequence, layout)
    assert 'id="edit"' in html and 'id="openChild"' in html
    assert "导出结构数据" in html and "设置下钻" in html


def test_parallel_flow_has_clear_column_headers_and_branch_labels():
    graph = {
        "schemaVersion": 1, "id": "branch", "title": "意图识别过程", "type": "flow", "direction": "LR",
        "layers": [{"id": "input", "name": "输入"}, {"id": "methods", "name": "并行识别"}, {"id": "output", "name": "结果汇总"}],
        "nodes": [
            {"id": "in", "layer": "input", "title": "用户诉求", "desc": "原始输入", "status": "implemented"},
            {"id": "a", "layer": "methods", "title": "关键词匹配", "desc": "规则判断", "status": "implemented", "order": 1},
            {"id": "b", "layer": "methods", "title": "语义分类", "desc": "理解表达", "status": "implemented", "order": 2},
            {"id": "c", "layer": "methods", "title": "相似度匹配", "desc": "查找样例", "status": "implemented", "order": 3},
            {"id": "out", "layer": "output", "title": "意图结果", "desc": "返回调度流程", "status": "implemented"},
        ],
        "edges": [
            {"id": "ia", "from": "in", "to": "a", "label": "规则判断", "kind": "call"},
            {"id": "ib", "from": "in", "to": "b", "label": "语义理解", "kind": "call"},
            {"id": "ic", "from": "in", "to": "c", "label": "向量比对", "kind": "call"},
            {"id": "ao", "from": "a", "to": "out", "label": "候选意图", "kind": "call"},
            {"id": "bo", "from": "b", "to": "out", "label": "候选意图", "kind": "call"},
            {"id": "co", "from": "c", "to": "out", "label": "候选意图", "kind": "call"},
        ],
    }
    layout = layout_diagram(graph, backend="builtin")
    layers = {layer["id"]: layer for layer in layout["layers"]}
    nodes = {node["id"]: node for node in layout["nodes"]}
    assert all(nodes[n["id"]]["y"] >= layers[n["layer"]]["y"] + 64 for n in graph["nodes"])
    assert max(edge["bends"] for edge in layout["edges"]) <= 1
    assert all("labelPosition" in edge for edge in layout["edges"])
    report = quality_report(graph, layout)
    assert report["passed"]
    assert report["counts"]["label_overlaps"] == 0
    assert report["counts"]["edge_crossings"] == 0


def test_parallel_flow_edges_between_nodes_in_same_column_are_orthogonal():
    graph = {
        "schemaVersion": 1, "id": "same-column", "title": "识别与融合", "type": "flow", "direction": "LR",
        "layers": [{"id": "input", "name": "输入"}, {"id": "result", "name": "结果"}],
        "nodes": [
            {"id": "input", "layer": "input", "title": "消息", "desc": "顾客当前诉求"},
            {"id": "short", "layer": "result", "title": "规则分数", "desc": "短"},
            {"id": "long", "layer": "result", "title": "融合后的识别结果", "desc": "较长标题用于验证同列卡片中心线保持一致"},
        ],
        "edges": [
            {"id": "to-short", "from": "input", "to": "short", "label": "规则结果", "kind": "call"},
            {"id": "to-long", "from": "input", "to": "long", "label": "识别结果", "kind": "call"},
            {"id": "within-column", "from": "short", "to": "long", "label": "汇总", "kind": "call"},
        ],
    }
    layout = layout_diagram(graph, backend="builtin")
    positions = {node["id"]: node for node in layout["nodes"]}
    assert positions["short"]["x"] + positions["short"]["width"] / 2 == positions["long"]["x"] + positions["long"]["width"] / 2
    report = quality_report(graph, layout)
    assert report["counts"]["diagonal_edges"] == 0


def test_single_architecture_layer_flow_uses_topological_detail_columns():
    graph = {
        "schemaVersion": 1, "id": "same-layer-chain", "title": "处理步骤", "type": "flow", "direction": "LR",
        "layers": [
            {"id": "L1", "name": "接入层"}, {"id": "L2", "name": "编排层"},
            {"id": "L3", "name": "能力层"}, {"id": "L4", "name": "业务服务层"},
        ],
        "nodes": [
            {"id": "intent", "layer": "L2", "title": "识别诉求", "desc": "融合规则与语义"},
            {"id": "state", "layer": "L2", "title": "补齐槽位", "desc": "恢复多轮上下文"},
            {"id": "dispatch", "layer": "L2", "title": "选择处理分支", "desc": "调度对应智能体"},
            {"id": "compose", "layer": "L2", "title": "合并回复", "desc": "汇总处理结果"},
        ],
        "edges": [
            {"id": "e1", "from": "intent", "to": "state", "label": "识别结果", "kind": "call"},
            {"id": "e2", "from": "state", "to": "dispatch", "label": "补齐请求", "kind": "call"},
            {"id": "e3", "from": "dispatch", "to": "compose", "label": "分支结果", "kind": "call"},
        ],
    }
    layout = layout_diagram(graph, hardcoded_ports=True)
    positions = {node["id"]: node for node in layout["nodes"]}
    ordered = ["intent", "state", "dispatch", "compose"]
    assert [positions[item]["x"] for item in ordered] == sorted(positions[item]["x"] for item in ordered)
    assert all(edge["bends"] == 0 for edge in layout["edges"])
    assert quality_report(graph, layout, hardcoded_ports=True)["passed"]


def test_flow_fan_in_to_single_storage_uses_straight_edges():
    graph = {
        "schemaVersion": 1, "id": "storage-fanin", "title": "本地业务数据读写", "type": "flow", "direction": "LR",
        "layers": [{"id": "readers", "name": "读写模块"}, {"id": "store", "name": "业务数据库"}],
        "nodes": [
            {"id": "chat", "layer": "readers", "title": "消息接口", "desc": "保存对话消息", "order": 1},
            {"id": "workbench", "layer": "readers", "title": "客服接口", "desc": "更新客服处理记录", "order": 2},
            {"id": "handoff", "layer": "readers", "title": "接管服务", "desc": "保存人工接管状态", "order": 3},
            {"id": "audit", "layer": "readers", "title": "审计记录", "desc": "保存操作与调用轨迹", "order": 4},
            {"id": "sqlite", "layer": "store", "title": "本地业务数据库", "desc": "保存会话、工单、风险与审计数据"},
        ],
        "edges": [
            {"id": "chat-write", "from": "chat", "to": "sqlite", "label": "保存消息", "kind": "db_write"},
            {"id": "workbench-write", "from": "workbench", "to": "sqlite", "label": "更新工单", "kind": "db_write"},
            {"id": "handoff-write", "from": "handoff", "to": "sqlite", "label": "保存接管", "kind": "db_write"},
            {"id": "audit-write", "from": "audit", "to": "sqlite", "label": "记录审计", "kind": "db_write"},
        ],
    }
    layout = layout_diagram(graph, backend="builtin")
    nodes = {node["id"]: node for node in layout["nodes"]}
    assert nodes["sqlite"]["height"] >= sum(nodes[item]["height"] for item in ("chat", "workbench", "handoff", "audit"))
    assert all(edge["bends"] == 0 for edge in layout["edges"])
    report = quality_report(graph, layout)
    assert report["passed"]
    assert report["counts"]["edge_crossings"] == 0
    assert report["counts"]["node_overlaps"] == 0
    assert report["counts"]["label_overlaps"] == 0
