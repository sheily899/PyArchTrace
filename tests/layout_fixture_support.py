"""Normalize frozen legacy regression IRs into the current test contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


FIXTURES = ROOT / "tests" / "layout_fixtures"


def _evidence_from(edges: list[dict], fallback: str) -> list[dict]:
    found = []
    seen = set()
    for edge in edges:
        for item in edge.get("evidence", []):
            path = item.get("path") if isinstance(item, dict) else None
            if path and path not in seen:
                found.append(item)
                seen.add(path)
    return found or [{"path": fallback, "line": 1}]


def _standard_type(layer: dict) -> str:
    text = f"{layer.get('id', '')} {layer.get('name', '')}"
    for token, value in (("治理", "governance"), ("接入", "access"), ("入口", "access"),
                         ("編排", "orchestration"), ("编排", "orchestration"),
                         ("能力", "capability"), ("業務", "business"), ("业务", "business"),
                         ("數據", "data"), ("数据", "data"), ("存儲", "data"), ("存储", "data")):
        if token in text:
            return value
    return "other"


def _main_chain(nodes: list[dict], edges: list[dict]) -> list[str]:
    ids = {node["id"] for node in nodes}
    ordered = sorted(edges, key=lambda edge: (edge.get("order", 10**9), edge.get("id", "")))
    path: list[str] = []
    for edge in ordered:
        if edge.get("from") not in ids or edge.get("to") not in ids:
            continue
        if not path:
            path.append(edge["from"])
        if path[-1] == edge["from"] and edge["to"] not in path:
            path.append(edge["to"])
        if len(path) == 7:
            break
    return path or ([nodes[0]["id"]] if nodes else [])


def _fill_test_details(graph: dict) -> None:
    for node in graph.get("nodes", []):
        node.setdefault("details", {
            "summary": "合成布局压力测试节点",
            "responsibilities": ["验证卡片布局"],
            "inputs": [], "outputs": [], "depends_on": [], "used_by": [],
            "key_files": [ref.get("path", "") for ref in node.get("evidence", []) if isinstance(ref, dict)],
            "tech": [], "confidence": {"evidence": [], "inference": [], "pending": []},
        })
    for child in graph.get("subDiagrams", []):
        _fill_test_details(child)


def _normalize_fixture(raw: dict) -> tuple[dict, dict]:
    diagram = json.loads(json.dumps(raw["diagram"], ensure_ascii=False))
    case_id = raw["caseId"]
    expected_template = raw.get("target", {}).get("expectedTemplate", "A")
    old_edges = diagram.get("edges", [])
    old_layers = diagram.get("layers", [])
    old_nodes = diagram.get("nodes", [])
    layer_by_id = {layer["id"]: layer for layer in old_layers}

    for layer in old_layers:
        layer["standardType"] = _standard_type(layer)
        if layer.get("crossCutting") or "治理" in layer.get("name", ""):
            layer["crossCutting"] = True
            layer["standardType"] = "governance"
            if "贯穿所有层" not in layer.get("desc", ""):
                layer["desc"] = "贯穿所有层"
        members = [node for node in old_nodes if node.get("layer") == layer["id"]]
        if len(members) >= 11 and any(not node.get("group") for node in members):
            for index, node in enumerate(members):
                node["group"] = ("入口" if index < len(members) // 3 else
                                 "处理" if index < 2 * len(members) // 3 else "结果")
    for node in old_nodes:
        desc = "".join(str(node.get("desc", "")).split())
        if len(desc) > 12 or "…" in desc or "..." in desc:
            node["desc"] = "处理业务请求"
        if len("".join(str(node.get("title", "")).split())) > 10 and case_id != "title-over-ten":
            node["title"] = node["title"][:10]

    layout: dict = {"contractVersion": 2}
    if case_id in {"layer-twelve"}:
        for layer in old_layers:
            members = [node for node in old_nodes if node.get("layer") == layer["id"]]
            if len(members) >= 11:
                for index, node in enumerate(members):
                    node["group"] = ("入口" if index < 4 else "处理" if index < 8 else "结果")
    if case_id == "seven-layers":
        ordinary = [layer for layer in old_layers if not layer.get("crossCutting")]
        merged_source_ids = [ordinary[2]["id"], ordinary[3]["id"]]
        layout["layerMerges"] = [{"id": "merged-3-4", "name": "能力业务", "desc": "合并职责域",
                                  "standardType": "other", "sourceLayerIds": merged_source_ids,
                                  "rationale": "合成用例声明相邻职责可合并，仅用于验证版面映射",
                                  "evidence": [{"path": f"tests/layout_fixtures/{case_id}.json", "line": 1}]}]
    if expected_template == "B":
        group_specs = []
        for layer in old_layers:
            members = [node["id"] for node in old_nodes if node.get("layer") == layer["id"]]
            pipeline_id = layer.get("id")
            group_specs.append({"id": pipeline_id, "name": layer["name"], "nodeIds": members,
                                "evidence": [{"path": f"tests/layout_fixtures/{case_id}.json", "line": 1}]})
        layout["pipelineGroups"] = group_specs
        layout["pipelineMerge"] = {"id": "pipeline-merge", "from": "offline", "to": "online",
                                    "label": "汇入在线", "evidence": [{"path": f"tests/layout_fixtures/{case_id}.json", "line": 1}]}
    if expected_template == "C":
        members = [node["id"] for node in old_nodes]
        chunks = [members[i::4] for i in range(min(4, len(members)))]
        keys = ["publicApi", "kernel", "extensions", "tooling"]
        names = ["公共接口", "核心内核", "适配扩展", "开发工具"]
        layout["projectKind"] = "library"
        layout["kernelGroups"] = {
            key: {"name": names[index], "nodeIds": chunk,
                  "evidence": [{"path": f"tests/layout_fixtures/{case_id}.json", "line": 1}]}
            for index, (key, chunk) in enumerate(zip(keys, chunks)) if chunk
        }
    if expected_template == "D":
        members = [node["id"] for node in old_nodes]
        chunks = [members[i::3] for i in range(min(3, len(members)))]
        layout["deploymentZones"] = [
            {"id": f"zone-{i+1}", "name": name, "nodeIds": chunk,
             "evidence": [{"path": f"tests/layout_fixtures/{case_id}.json", "line": 1}]}
            for i, (name, chunk) in enumerate(zip(("入口区域", "服务区域", "数据区域"), chunks)) if chunk
        ]

    display_ids = [layer["id"] for layer in old_layers if not layer.get("crossCutting")]
    if expected_template == "A" and layout.get("layerMerges"):
        merge = layout["layerMerges"][0]
        display_ids = [layer_id for layer_id in display_ids if layer_id not in merge["sourceLayerIds"]]
        display_ids.insert(min(old_layers.index(layer_by_id[source]) for source in merge["sourceLayerIds"]), merge["id"])
    elif expected_template == "B":
        display_ids = [group["id"] for group in layout["pipelineGroups"]]
    elif expected_template == "C":
        display_ids = list(layout["kernelGroups"])
    elif expected_template == "D":
        display_ids = [zone["id"] for zone in layout["deploymentZones"]]

    source_to_display = {layer_id: layer_id for layer_id in display_ids}
    if expected_template == "A" and layout.get("layerMerges"):
        merge = layout["layerMerges"][0]
        for source in merge["sourceLayerIds"]:
            source_to_display[source] = merge["id"]
    flows = []
    for index, (from_layer, to_layer) in enumerate(zip(display_ids, display_ids[1:])):
        evidence_edges = []
        for edge in old_edges:
            source = next((node for node in old_nodes if node.get("id") == edge.get("from")), {})
            target = next((node for node in old_nodes if node.get("id") == edge.get("to")), {})
            if (source_to_display.get(source.get("layer")) == from_layer
                    and source_to_display.get(target.get("layer")) == to_layer):
                evidence_edges.append(edge)
        if evidence_edges:
            flows.append({"id": f"layer-flow-{index+1}", "fromLayer": from_layer, "toLayer": to_layer,
                          "label": "请求流转", "evidence": _evidence_from(evidence_edges, f"tests/layout_fixtures/{case_id}.json")})

    diagram["template"] = expected_template
    diagram["mainChain"] = _main_chain(old_nodes, old_edges)
    diagram["layerFlows"] = flows
    if case_id != "many-cross-layer-relations":
        diagram["edges"] = []
    diagram["showEdgeLabels"] = False
    diagram["layout"] = layout
    _fill_test_details(diagram)
    return diagram, {"expectedTemplate": expected_template}
