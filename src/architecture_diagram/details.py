"""从代码证据和关系清单填充模块详情中的派生字段。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_SEMANTIC_FIELDS = ("summary", "responsibilities", "inputs", "outputs")


def _evidence_strings(refs: list[dict]) -> list[str]:
    result = []
    for ref in refs:
        path = str(ref.get("path", "")).strip()
        if not path:
            continue
        location = f":{ref['line']}" if isinstance(ref.get("line"), int) else ""
        claim = str(ref.get("claim", "")).strip()
        result.append(f"{path}{location}{' ' + claim if claim else ''}")
    return sorted(set(result))


def enrich_diagram_details(diagram: dict, analysis: dict, facts: dict) -> dict:
    """保留模型给出的语义字段；依赖、文件、技术栈和置信度由证据确定性生成。"""
    result = deepcopy(diagram)
    modules = {item["id"]: item for item in analysis.get("stageB", {}).get("modules", [])}
    relations = {item["id"]: item for item in analysis.get("stageC", {}).get("relations", [])}
    facts_by_path = {item.get("path"): item for item in facts.get("modules", [])}

    def walk(graph: dict) -> None:
        graph_nodes = {node.get("id"): node for node in graph.get("nodes", [])}
        incoming: dict[str, set[str]] = {node_id: set() for node_id in graph_nodes}
        outgoing: dict[str, set[str]] = {node_id: set() for node_id in graph_nodes}
        for edge in graph.get("edges", []):
            if edge.get("relationIds"):
                unknown = set(edge["relationIds"]) - relations.keys()
                if unknown:
                    raise ValueError(f"图 {graph.get('id')} 的关系引用不存在：{', '.join(sorted(unknown))}")
            if edge.get("from") in outgoing and edge.get("to") in incoming:
                outgoing[edge["from"]].add(edge["to"])
                incoming[edge["to"]].add(edge["from"])

        for node in graph.get("nodes", []):
            node_id = node.get("id")
            details = node.get("details")
            if not isinstance(details, dict):
                raise ValueError(f"节点 {node_id} 缺少模型语义详情 details")
            for field in _SEMANTIC_FIELDS:
                value = details.get(field)
                if field == "responsibilities":
                    if not isinstance(value, list) or len(value) > 4 or any(not str(item).strip() for item in value):
                        raise ValueError(f"节点 {node_id} 的 details.responsibilities 必须为 1 至 4 条非空职责")
                elif field in {"inputs", "outputs"}:
                    if not isinstance(value, list) or any(not str(item).strip() for item in value):
                        raise ValueError(f"节点 {node_id} 的 details.{field} 必须为字符串数组")
                elif not isinstance(value, str) or not value.strip():
                    raise ValueError(f"节点 {node_id} 缺少非空 details.{field}")

            module = modules.get(node_id, {})
            evidence = module.get("evidence") or node.get("evidence") or []
            key_files = sorted({str(ref["path"]) for ref in evidence if isinstance(ref, dict) and ref.get("path")})
            technologies = set()
            for path in key_files:
                fact = facts_by_path.get(path, {})
                for imported in fact.get("imports", []):
                    name = str(imported.get("module", "")).strip().lstrip(".")
                    if name:
                        technologies.add(name.split(".", 1)[0])
            if node_id in modules:
                depends_on = {item.get("to") for item in relations.values() if item.get("from") == node_id}
                used_by = {item.get("from") for item in relations.values() if item.get("to") == node_id}
            else:
                depends_on = outgoing.get(node_id, set())
                used_by = incoming.get(node_id, set())
            details["depends_on"] = sorted(item for item in depends_on if item and item != node_id)
            details["used_by"] = sorted(item for item in used_by if item and item != node_id)
            details["key_files"] = key_files
            details["tech"] = sorted(technologies)
            details["confidence"] = {
                "evidence": _evidence_strings(evidence),
                "inference": [],
                "pending": [],
            }

        for child in graph.get("subDiagrams", []):
            walk(child)

    walk(result)
    return result


def details_consistency_errors(diagram: dict, analysis: dict, facts: dict) -> list[str]:
    """核对已填详情中的代码派生字段是否与关系/事实清单一致。"""
    expected = enrich_diagram_details(diagram, analysis, facts)
    errors: list[str] = []

    def walk(actual: dict, derived: dict) -> None:
        expected_by_id = {node.get("id"): node for node in derived.get("nodes", [])}
        for node in actual.get("nodes", []):
            generated = expected_by_id.get(node.get("id"), {})
            actual_details = node.get("details") if isinstance(node.get("details"), dict) else {}
            expected_details = generated.get("details", {})
            for field in ("depends_on", "used_by", "key_files", "tech", "confidence"):
                if actual_details.get(field) != expected_details.get(field):
                    errors.append(f"节点 {node.get('id')} 的 details.{field} 与代码派生结果不一致；请重新运行 enrich-details")
        actual_children = {item.get("id"): item for item in actual.get("subDiagrams", [])}
        for child in derived.get("subDiagrams", []):
            sibling = actual_children.get(child.get("id"))
            if sibling:
                walk(sibling, child)

    walk(diagram, expected)
    return errors
