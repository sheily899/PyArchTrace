from __future__ import annotations

import json
from pathlib import Path

import pytest

from architecture_diagram.layout import layout_diagram
from architecture_diagram.quality import quality_report
from architecture_diagram.render import render_svg


FIXTURES = Path(__file__).parent / "layout_fixtures"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))["diagram"]


@pytest.mark.parametrize("name,count", [("fan-out-2", 2), ("fan-out-3", 3), ("fan-out-5", 5)])
def test_fan_out_uses_one_bus_and_visible_target_arrows(name: str, count: int):
    graph = _fixture(name)
    layout = layout_diagram(graph, backend="builtin", hardcoded_ports=True)

    assert len(layout["edgeGroups"]) == 1
    group = layout["edgeGroups"][0]
    assert group["pattern"] == "fan_out"
    assert len(group["edgeIds"]) == count
    assert group["trunkPoints"]
    assert all(layout_edge["groupId"] == group["id"] for layout_edge in layout["edges"])
    assert sum(layout_edge["showMarker"] for layout_edge in layout["edges"]) == count
    assert all(layout_edge["labelPosition"] is None for layout_edge in layout["edges"]) if count >= 3 else True
    svg = render_svg(graph, layout)
    if count >= 3:
        assert 'class="edge-label"' not in svg
        assert 'class="route-annotation"' in svg
    report = quality_report(graph, layout, hardcoded_ports=True)
    assert report["passed"], report["issues"]
    assert report["counts"]["branch_group_violations"] == 0


def test_fan_in_seven_puts_usage_on_sources_and_draws_one_target_arrow():
    graph = _fixture("fan-in-seven")
    layout = layout_diagram(graph, backend="builtin", hardcoded_ports=True)
    group = layout["edgeGroups"][0]
    source_layer = next(node["layer"] for node in layout["nodes"] if node["id"] == graph["edges"][0]["from"])
    target_layer = next(node["layer"] for node in layout["nodes"] if node["id"] == graph["edges"][0]["to"])
    lanes = {lane["id"]: lane for lane in layout["layers"]}
    channel_left = lanes[source_layer]["x"] + lanes[source_layer]["width"]
    channel_right = lanes[target_layer]["x"]

    assert group["pattern"] == "fan_in"
    assert channel_left < group["busX"] < channel_right
    assert group["busX"] == pytest.approx((channel_left + channel_right) / 2)
    assert group["targetArrowPoints"]
    assert sum(edge["showMarker"] for edge in layout["edges"]) == 0
    assert all(edge["labelPosition"] is None for edge in layout["edges"])
    annotations = {node["id"]: node.get("routeAnnotationLines", []) for node in layout["nodes"]}
    assert all(annotations[f"source-{index}"] for index in range(1, 8))
    svg = render_svg(graph, layout)
    assert svg.count('class="edge-group-arrow"') == 1
    assert 'stroke="#64748B" stroke-width="1.8"' in svg
    assert 'marker-end="url(#arrow-64748B)"' in svg
    assert 'id="arrow-64748B"' in svg and 'fill="#64748B"' in svg
    report = quality_report(graph, layout, hardcoded_ports=True)
    assert report["passed"], report["issues"]
    assert report["counts"]["visible_arrow_count"] == 1


def test_fan_in_source_tags_share_fixed_card_height_with_complete_description():
    graph = _fixture("fan-in-seven")
    for node in graph["nodes"]:
        if node["id"].startswith("source-"):
            node["desc"] = "长期维护会话状态并提供完整调用上下文"

    layout = layout_diagram(graph, backend="builtin", hardcoded_ports=True)
    annotated = [node for node in layout["nodes"] if node.get("routeAnnotationLines")]

    assert len(annotated) == 7
    assert all(node["height"] == 68 for node in annotated)
    assert all(len(node["desc_lines"]) == 1 for node in annotated)
    assert all(len(node["routeAnnotationLines"]) <= 2 for node in annotated)
    assert quality_report(graph, layout, hardcoded_ports=True)["passed"]


def test_many_to_many_automatically_uses_relation_matrix():
    graph = _fixture("many-to-many-three")
    layout = layout_diagram(graph, backend="builtin", hardcoded_ports=True)
    svg = render_svg(graph, layout)

    assert layout["viewMode"] == "relation_matrix"
    assert len(layout["matrix"]["cells"]) == 9
    assert 'data-view-mode="relation-matrix"' in svg
    assert svg.count('data-relation-cell=') == 9
    assert quality_report(graph, layout, hardcoded_ports=True)["passed"]


def test_datasette_query_api_three_way_fan_out_keeps_labels_on_source_card():
    fixture = json.loads((FIXTURES / "datasette-baseline.json").read_text(encoding="utf-8"))

    def find(graph: dict, graph_id: str) -> dict | None:
        if graph.get("id") == graph_id:
            return graph
        for child in graph.get("subDiagrams", []):
            result = find(child, graph_id)
            if result:
                return result
        return None

    graph = find(fixture["diagram"], "sql-query")
    assert graph is not None
    layout = layout_diagram(graph, backend="builtin", hardcoded_ports=True)
    group = next(item for item in layout["edgeGroups"] if item["pattern"] == "fan_out")

    assert len(group["edgeIds"]) == 3
    assert all(not edge["showLabel"] and edge["labelPosition"] is None for edge in layout["edges"]
               if edge["groupId"] == group["id"])
    source = next(node for node in layout["nodes"] if node["id"] == group["sourceId"])
    assert len(source["routeAnnotationLines"]) <= 2
    report = quality_report(graph, layout, hardcoded_ports=True)
    assert report["passed"], report["issues"]
    assert layout["width"] <= 1600


def test_datasette_fan_out_bus_uses_the_reserved_gap_between_layers():
    fixture = json.loads((FIXTURES / "datasette-baseline.json").read_text(encoding="utf-8"))

    def find(graph: dict, graph_id: str) -> dict | None:
        if graph.get("id") == graph_id:
            return graph
        for child in graph.get("subDiagrams", []):
            result = find(child, graph_id)
            if result:
                return result
        return None

    graph = find(fixture["diagram"], "sql-query")
    assert graph is not None
    layout = layout_diagram(graph, backend="builtin", hardcoded_ports=True)
    group = next(item for item in layout["edgeGroups"] if item["pattern"] == "fan_out")
    source = next(node for node in layout["nodes"] if node["id"] == group["sourceId"])
    target_id = next(edge["to"] for edge in graph["edges"] if edge["id"] == group["edgeIds"][0])
    target = next(node for node in layout["nodes"] if node["id"] == target_id)
    lanes = {lane["id"]: lane for lane in layout["layers"]}
    source_lane, target_lane = lanes[source["layer"]], lanes[target["layer"]]
    channel_left = source_lane["x"] + source_lane["width"]
    channel_right = target_lane["x"]

    assert channel_left < group["busX"] < channel_right
    assert group["busX"] == pytest.approx((channel_left + channel_right) / 2)


def test_fan_out_shared_trunk_visibly_reaches_every_branch():
    fixture = json.loads((FIXTURES / "datasette-baseline.json").read_text(encoding="utf-8"))

    def find(graph: dict, graph_id: str) -> dict | None:
        if graph.get("id") == graph_id:
            return graph
        for child in graph.get("subDiagrams", []):
            result = find(child, graph_id)
            if result:
                return result
        return None

    graph = find(fixture["diagram"], "sql-query")
    assert graph is not None
    layout = layout_diagram(graph, backend="builtin", hardcoded_ports=True)
    group = next(item for item in layout["edgeGroups"] if item["pattern"] == "fan_out")
    bus_x = group["busX"]
    trunk = group["trunkPoints"]
    vertical_spans = [
        sorted((first["y"], second["y"]))
        for first, second in zip(trunk, trunk[1:])
        if first["x"] == second["x"] == bus_x
    ]
    branch_ys = [group["branchPoints"][edge_id][0]["y"] for edge_id in group["edgeIds"]]

    assert len(branch_ys) == 3
    assert all(any(start <= y <= end for start, end in vertical_spans) for y in branch_ys)


def test_branch_audit_rejects_a_shared_trunk_that_misses_a_branch():
    fixture = json.loads((FIXTURES / "datasette-baseline.json").read_text(encoding="utf-8"))

    def find(graph: dict, graph_id: str) -> dict | None:
        if graph.get("id") == graph_id:
            return graph
        for child in graph.get("subDiagrams", []):
            result = find(child, graph_id)
            if result:
                return result
        return None

    graph = find(fixture["diagram"], "sql-query")
    assert graph is not None
    layout = layout_diagram(graph, backend="builtin", hardcoded_ports=True)
    group = next(item for item in layout["edgeGroups"] if item["pattern"] == "fan_out")
    group["trunkPoints"] = group["trunkPoints"][:2] + [group["trunkPoints"][-1]]

    report = quality_report(graph, layout, hardcoded_ports=True)

    assert report["passed"] is False
    assert any(issue["code"] == "branch_group_invalid"
               and "fan_out_branch_disconnected" in issue["group"] for issue in report["issues"])


def test_branch_audit_rejects_a_bus_outside_the_reserved_layer_channel():
    fixture = json.loads((FIXTURES / "datasette-baseline.json").read_text(encoding="utf-8"))

    def find(graph: dict, graph_id: str) -> dict | None:
        if graph.get("id") == graph_id:
            return graph
        for child in graph.get("subDiagrams", []):
            result = find(child, graph_id)
            if result:
                return result
        return None

    graph = find(fixture["diagram"], "sql-query")
    assert graph is not None
    layout = layout_diagram(graph, backend="builtin", hardcoded_ports=True)
    group = next(item for item in layout["edgeGroups"] if item["pattern"] == "fan_out")
    source = next(node for node in layout["nodes"] if node["id"] == group["sourceId"])
    group["busX"] = source["x"] + source["width"] + 4

    report = quality_report(graph, layout, hardcoded_ports=True)

    assert report["passed"] is False
    assert any(issue["code"] == "branch_group_invalid"
               and "fan_out_bus_outside_channel" in issue["group"] for issue in report["issues"])


def test_bidirectional_pair_uses_parallel_tracks_and_return_legend():
    graph = _fixture("bidirectional-two")
    layout = layout_diagram(graph, backend="builtin", hardcoded_ports=True)

    assert len(layout["edgeGroups"]) == 1
    assert layout["edgeGroups"][0]["pattern"] == "bidirectional"
    assert sum(bool(edge.get("returnEdge")) for edge in layout["edges"]) == 1
    assert quality_report(graph, layout, hardcoded_ports=True)["passed"]
    assert 'data-legend-key="return"' in render_svg(graph, layout)


def test_long_single_edge_label_gets_a_bay_and_stays_close_to_its_line():
    graph = _fixture("long-label")
    layout = layout_diagram(graph, backend="builtin", hardcoded_ports=True)
    report = quality_report(graph, layout, hardcoded_ports=True)

    assert report["passed"], report["issues"]
    assert layout["edges"][0]["labelPosition"]
    assert report["counts"]["label_distance_violations"] == 0


def test_sequence_return_semantics_remain_unchanged():
    graph = _fixture("sequence-return")
    layout = layout_diagram(graph)

    assert not layout.get("edgeGroups")
    assert len(layout["edges"]) == 4
    assert quality_report(graph, layout)["passed"]
