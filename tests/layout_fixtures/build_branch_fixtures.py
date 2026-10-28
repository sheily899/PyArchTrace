"""Build deterministic synthetic fixtures for branch-routing baselines."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent


def ev(case: str) -> list[dict]:
    return [{"path": f"tests/layout_fixtures/{case}.json", "line": 1,
             "claim": "合成连线压力样例；不代表真实代码证据"}]


def flow(case: str, title: str, left: list[tuple[str, str]], right: list[tuple[str, str]],
         pairs: list[tuple[int, int]], *, labels: list[str] | None = None) -> dict:
    layers = [{"id": "source", "name": "调用方"}, {"id": "target", "name": "目标能力"}]
    nodes = []
    for layer, items in (("source", left), ("target", right)):
        for index, (name, desc) in enumerate(items):
            nodes.append({"id": f"{layer}-{index + 1}", "layer": layer, "title": name,
                          "desc": desc, "status": "implemented", "order": index,
                          "evidence": ev(case)})
    edges = []
    for index, (source, target) in enumerate(pairs):
        edges.append({"id": f"e{index + 1}", "from": f"source-{source + 1}",
                      "to": f"target-{target + 1}",
                      "label": labels[index] if labels else f"处理分支{index + 1}",
                      "kind": "call", "main": True, "evidence": ev(case)})
    return {"schemaVersion": 1, "id": case, "title": title, "type": "flow", "direction": "LR",
            "layers": layers, "nodes": nodes, "edges": edges, "subDiagrams": []}


def write(case: str, diagram: dict, expected: str) -> None:
    payload = {"caseId": case, "diagram": diagram,
               "target": {"routingPattern": expected, "kind": "合成分支路由基线"}}
    (FIXTURES / f"{case}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    for count in (2, 3, 5):
        pairs = [(0, index) for index in range(count)]
        diagram = flow(f"fan-out-{count}", f"一对{count}扇出",
                       [("查询接口", "分发业务请求")],
                       [(f"业务模块{index + 1}", "处理对应业务") for index in range(count)], pairs)
        write(f"fan-out-{count}", diagram, "fan_out_bus")

    fan_in = flow("fan-in-seven", "七对一汇入",
                  [(f"业务模块{index + 1}", "提交模型请求") for index in range(7)],
                  [("语言模型", "返回生成结果")], [(index, 0) for index in range(7)],
                  labels=["语义分类", "意图识别", "回复生成", "摘要生成", "风险判断", "查询改写", "内容审核"])
    write("fan-in-seven", fan_in, "fan_in_bus")

    complete = [(source, target) for source in range(3) for target in range(3)]
    write("many-to-many-three", flow(
        "many-to-many-three", "三对三关系网",
        [(f"调用方{index + 1}", "提交处理请求") for index in range(3)],
        [(f"处理模块{index + 1}", "返回处理结果") for index in range(3)], complete), "split_or_matrix")

    bidirectional = flow("bidirectional-two", "双向调用",
                         [("前端页面", "发起服务请求")], [("业务接口", "返回查询结果")],
                         [(0, 0), (0, 0)], labels=["提交请求", "返回结果"])
    bidirectional["edges"][1]["from"], bidirectional["edges"][1]["to"] = (
        bidirectional["edges"][1]["to"], bidirectional["edges"][1]["from"])
    write("bidirectional-two", bidirectional, "parallel_opposite_directions")

    sequence = {
        "schemaVersion": 1, "id": "sequence-return", "title": "同步调用与结果返回",
        "type": "sequence", "direction": "TB", "layers": [],
        "nodes": [
            {"id": "client", "title": "调用方", "desc": "发起查询", "status": "implemented", "evidence": ev("sequence-return")},
            {"id": "service", "title": "业务服务", "desc": "处理请求", "status": "implemented", "evidence": ev("sequence-return")},
            {"id": "store", "title": "数据存储", "desc": "读取记录", "status": "implemented", "evidence": ev("sequence-return")},
        ],
        "edges": [
            {"id": "q1", "from": "client", "to": "service", "label": "查询请求", "kind": "message", "order": 1, "evidence": ev("sequence-return")},
            {"id": "q2", "from": "service", "to": "store", "label": "读取数据", "kind": "message", "order": 2, "evidence": ev("sequence-return")},
            {"id": "r1", "from": "store", "to": "service", "label": "查询结果", "kind": "message", "order": 3, "evidence": ev("sequence-return")},
            {"id": "r2", "from": "service", "to": "client", "label": "返回响应", "kind": "message", "order": 4, "evidence": ev("sequence-return")},
        ], "subDiagrams": [],
    }
    write("sequence-return", sequence, "sequence_with_return")

    long_label = flow("long-label", "长标签关系",
                      [("会话管理", "整理用户当前上下文")],
                      [("知识检索", "查找相关业务知识")], [(0, 0)],
                      labels=["合并用户问题与会话历史后生成完整检索条件"])
    write("long-label", long_label, "single_edge_label_no_overlap")


if __name__ == "__main__":
    main()
