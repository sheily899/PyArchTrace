"""Generate deterministic synthetic layout pressure fixtures.

Run from the repository root:
    python tests/layout_fixtures/build_fixtures.py

Synthetic evidence references identify fixture records only; they are not claims
about a real codebase. Reviewed project fixtures are checked in separately.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


FIXTURE_DIR = Path(__file__).resolve().parent
LAYER_NAMES = ["接入层", "编排层", "能力层", "业务服务层", "数据层", "扩展层", "运行层"]
NODE_NAMES = [
    "请求接收", "会话管理", "路由分发", "任务协调", "数据查询", "结果整理", "权限校验",
    "配置加载", "记录保存", "状态更新", "服务调用", "输出处理", "数据读取", "任务创建",
    "异常处理", "日志记录", "页面渲染", "模型调用", "插件管理", "文件存取",
]


def _evidence(case_id: str, claim: str) -> list[dict]:
    return [{"path": f"tests/layout_fixtures/{case_id}.json", "line": 1, "claim": claim}]


def _diagram(case_id: str, layer_counts: Iterable[int], *, governance: bool = False,
             edge_count: int = 0, title_overrides: dict[int, str] | None = None,
             layer_names: list[str] | None = None, expected_template: str = "A",
             offline_online: bool = False, node_groups: bool = False) -> dict:
    counts = list(layer_counts)
    names = layer_names or LAYER_NAMES[:len(counts)]
    layers = [{"id": f"L{i + 1}", "name": name, "desc": "承接本层主要职责"}
              for i, name in enumerate(names)]
    if governance:
        layers.append({"id": "GOV", "name": "治理层", "desc": "身份安全与运行审计", "crossCutting": True})

    nodes = []
    layer_node_ids: list[list[str]] = []
    global_index = 0
    for layer_index, count in enumerate(counts):
        ids = []
        for local_index in range(count):
            global_index += 1
            node_id = f"n{global_index:02d}"
            title = NODE_NAMES[(global_index - 1) % len(NODE_NAMES)]
            if title_overrides and global_index in title_overrides:
                title = title_overrides[global_index]
            node = {
                "id": node_id,
                "layer": f"L{layer_index + 1}",
                "title": title,
                "desc": "承接业务处理",
                "status": "implemented",
                "order": local_index,
                "evidence": _evidence(case_id, "合成布局压力样例；不代表真实代码证据"),
            }
            if node_groups and count >= 11:
                node["group"] = f"组{local_index // 3 + 1}"
            nodes.append(node)
            ids.append(node_id)
        layer_node_ids.append(ids)

    if governance:
        for index, name in enumerate(["身份校验", "回复保护", "审计记录", "调用监控"]):
            global_index += 1
            nodes.append({
                "id": f"g{index + 1}", "layer": "GOV", "title": name, "desc": "提供横向保障",
                "status": "implemented", "order": index,
                "evidence": _evidence(case_id, "合成布局压力样例；不代表真实代码证据"),
            })

    edges = []
    pairs = []
    if len(layer_node_ids) > 1:
        for source_layer, target_layer in zip(layer_node_ids, layer_node_ids[1:]):
            pairs.append((source_layer[0], target_layer[0]))
    if edge_count and layer_node_ids:
        all_pairs = []
        for source_index in range(len(layer_node_ids) - 1):
            left, right = layer_node_ids[source_index], layer_node_ids[source_index + 1]
            for source in left:
                for target in right:
                    all_pairs.append((source, target))
        if not all_pairs:
            all_pairs = [(ids[0], ids[-1]) for ids in layer_node_ids if len(ids) > 1]
        pairs.extend(all_pairs[i % len(all_pairs)] for i in range(max(0, edge_count - len(pairs))))
    seen = set()
    for source, target in pairs:
        key = (source, target)
        if key in seen:
            continue
        seen.add(key)
        edges.append({
            "id": f"e{len(edges) + 1:02d}", "from": source, "to": target,
            "label": "", "kind": "call", "main": True,
            "evidence": _evidence(case_id, "合成布局压力样例；不代表真实代码证据"),
        })
        if len(edges) >= edge_count:
            break

    title = "离线与在线双链路" if offline_online else "布局压力样例"
    diagram = {
        "schemaVersion": 1,
        "id": case_id,
        "title": title,
        "type": "architecture",
        "direction": "TB",
        "layers": layers,
        "nodes": nodes,
        "edges": edges,
        "showEdgeLabels": False,
        "layout": {"fixtureExpectedTemplate": expected_template},
    }
    if offline_online:
        diagram["layers"] = [
            {"id": "offline", "name": "离线处理", "desc": "批量准备和索引"},
            {"id": "online", "name": "在线服务", "desc": "请求查询和结果返回"},
        ]
        for node in diagram["nodes"]:
            node["layer"] = "offline" if int(node["id"][1:]) <= counts[0] else "online"
    return diagram


def _write_fixture(case_id: str, diagram: dict, target: dict) -> None:
    path = FIXTURE_DIR / f"{case_id}.json"
    payload = {"caseId": case_id, "diagram": diagram, "target": target}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    cases = [
        ("singleton-layer", [1, 5, 6], True, 2, {}, ["接入层", "编排层", "数据层"], "A", False),
        ("layer-twelve", [12, 4, 4], False, 2, {}, None, "A", False),
        ("three-layers", [4, 4, 4], True, 2, None, None, "A", False),
        ("seven-layers", [2, 2, 2, 2, 2, 2, 2], True, 6, None, None, "A", False),
        ("title-exactly-ten", [4, 4, 4], False, 2, {1: "企业用户身份权限校验"}, None, "A", False),
        ("title-over-ten", [4, 4, 4], False, 2, {1: "企业用户身份权限规则校验"}, None, "A", False),
        ("no-governance", [4, 4, 4], False, 2, None, None, "A", False),
        ("thirty-modules", [5, 5, 5, 5, 5, 5], False, 5, None, None, "A", False),
        ("many-cross-layer-relations", [3, 3, 3, 3], True, 20, None, None, "A", False),
        ("pure-sdk", [12], False, 0, None, ["库组件"], "C", False),
        ("offline-online", [6, 6], False, 1, None, ["离线处理", "在线服务"], "B", True),
        ("misaligned-four-five", [4, 5, 3], True, 3, None, None, "A", False),
    ]
    for case_id, counts, governance, edge_count, titles, names, template, dual in cases:
        _write_fixture(case_id, _diagram(case_id, counts, governance=governance, edge_count=edge_count,
                                         title_overrides=titles, layer_names=names, expected_template=template,
                                         offline_online=dual, node_groups=case_id == "layer-twelve"),
                       {"expectedTemplate": template})

    for count in (2, 3, 4, 5, 6, 7, 9):
        case_id = f"layer-size-{count}"
        counts = [5, count, 5]
        _write_fixture(case_id, _diagram(case_id, counts, governance=False, edge_count=2),
                       {"targetLayerSize": count, "expectedTemplate": "A"})

    readme = """# 架构图布局压力测试集

这些 JSON 是布局回归输入。合成用例中的 `evidence` 仅用于验证 IR 结构与审计器行为，
不代表真实项目源码事实；本目录中的固定项目图仅用于跨项目布局回归，不规定生产图的领域、层名或模块结构。
本脚本只重建合成用例，不覆盖这些固定项目图。

重新生成：`python tests/layout_fixtures/build_fixtures.py`
运行当前契约与几何回归：`python -m pytest -q tests/test_layout_fixture_contract.py`

覆盖：单模块层、12 模块层、3/7 层、标题 10 字与超限、无治理层、30 模块、密集跨层关系、
SDK 内核扩展、离线在线双链路、每层 2/3/4/5/6/7/9 个模块及 4/5 相邻层错列。固定项目 IR 仅作回归，另行保存在本目录。
"""
    (FIXTURE_DIR / "README.md").write_text(readme, encoding="utf-8")


if __name__ == "__main__":
    main()
