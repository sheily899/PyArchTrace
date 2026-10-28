"""中间表示校验。内部 ID 与代码证据永不作为图面文字渲染。"""

from __future__ import annotations

import re
from typing import Any


class DiagramValidationError(ValueError):
    """图数据不符合本工具的结构或可视化规则。"""


_VISIBLE_LATIN = re.compile(r"[A-Za-z]{2,}")
_STATUSES = {"implemented", "partial", "config_only", "unknown"}
_TYPES = {"architecture", "sequence", "flow"}
_TEMPLATES = {"A", "B", "C", "D"}
_STANDARD_LAYER_TYPES = {"access", "orchestration", "capability", "business", "data", "governance", "other"}
_EDGE_KINDS = {
    "call", "http", "sse", "db_read", "db_write", "cache", "vector_query",
    "llm_call", "spawn_task", "message", "event", "governance", "other",
}


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _check_visible_text(value: Any, where: str, errors: list[str], *, allow_empty=False) -> None:
    if allow_empty and value == "":
        return
    if not _is_text(value):
        errors.append(f"{where} 必须是非空中文文本")
    elif _VISIBLE_LATIN.search(value):
        errors.append(f"{where} 含英文或代码痕迹；图面标签必须改成中文业务含义")


def validate_diagram(diagram: Any, *, _path: str = "主图") -> list[str]:
    """返回全部校验问题；结构错误不抛异常，便于 CLI 一次性报告。"""
    errors: list[str] = []
    if not isinstance(diagram, dict):
        return [f"{_path} 必须是 JSON 对象"]

    for key in ("schemaVersion", "id", "title", "type", "direction", "layers", "nodes", "edges"):
        if key not in diagram:
            errors.append(f"{_path} 缺少字段 {key}")
    if errors:
        return errors

    if diagram["schemaVersion"] != 1:
        errors.append(f"{_path} schemaVersion 目前只支持 1")
    if diagram["type"] not in _TYPES:
        errors.append(f"{_path} type 必须为 architecture、sequence 或 flow")
    if diagram["direction"] not in {"TB", "LR"}:
        errors.append(f"{_path} direction 必须为 TB 或 LR")
    _check_visible_text(diagram["title"], f"{_path}.title", errors)

    layers = diagram.get("layers")
    nodes = diagram.get("nodes")
    edges = diagram.get("edges")
    if not isinstance(layers, list) or not isinstance(nodes, list) or not isinstance(edges, list):
        return errors + [f"{_path} 的 layers、nodes、edges 必须是数组"]

    layer_ids: set[str] = set()
    for i, layer in enumerate(layers):
        if not isinstance(layer, dict) or not _is_text(layer.get("id")):
            errors.append(f"{_path}.layers[{i}] 缺少有效 id")
            continue
        if layer["id"] in layer_ids:
            errors.append(f"{_path} 存在重复层 ID：{layer['id']}")
        layer_ids.add(layer["id"])
        _check_visible_text(layer.get("name"), f"{_path}.layers[{i}].name", errors)
        if layer.get("desc"):
            _check_visible_text(layer["desc"], f"{_path}.layers[{i}].desc", errors)

    node_ids: set[str] = set()
    for i, node in enumerate(nodes):
        location = f"{_path}.nodes[{i}]"
        if not isinstance(node, dict) or not _is_text(node.get("id")):
            errors.append(f"{location} 缺少有效 id")
            continue
        if node["id"] in node_ids:
            errors.append(f"{_path} 存在重复节点 ID：{node['id']}")
        node_ids.add(node["id"])
        for field in ("title",):
            _check_visible_text(node.get(field), f"{location}.{field}", errors)
        _check_visible_text(node.get("desc", ""), f"{location}.desc", errors, allow_empty=True)
        if diagram["type"] == "architecture" and _path == "主图":
            description = "".join(str(node.get("desc", "")).split())
            if len(description) > 12 or "…" in description or "..." in description:
                errors.append(f"{location}.desc 主图说明必须不超过 12 字，且不得用省略号截断")
            title_length = len("".join(str(node.get("title", "")).split()))
            if title_length > 10:
                errors.append(f"{location}.title 主图卡片名超过 10 字，必须改写后再布局")
        if node.get("status", "implemented") not in _STATUSES:
            errors.append(f"{location}.status 状态值无效")
        if "column" in node and (not isinstance(node["column"], int) or isinstance(node["column"], bool) or node["column"] < 0):
            errors.append(f"{location}.column 必须是非负整数；它只表示语义对齐列，不是坐标")
        if diagram["type"] != "sequence" and node.get("layer") not in layer_ids:
            errors.append(f"{location} 的 layer 不存在；层内节点必须明确归层")
        for ref in node.get("evidence", []):
            if not isinstance(ref, dict) or not _is_text(ref.get("path")):
                errors.append(f"{location}.evidence 必须包含文件路径证据")

    edge_ids: set[str] = set()
    for i, edge in enumerate(edges):
        location = f"{_path}.edges[{i}]"
        if not isinstance(edge, dict) or not _is_text(edge.get("id")):
            errors.append(f"{location} 缺少有效 id")
            continue
        if edge["id"] in edge_ids:
            errors.append(f"{_path} 存在重复连线 ID：{edge['id']}")
        edge_ids.add(edge["id"])
        for endpoint in ("from", "to"):
            if edge.get(endpoint) not in node_ids:
                errors.append(f"{location} 端点 {edge.get(endpoint)!r} 不存在")
        _check_visible_text(edge.get("label"), f"{location}.label", errors,
                            allow_empty=diagram["type"] == "architecture" and _path == "主图")
        if edge.get("kind", "other") not in _EDGE_KINDS:
            errors.append(f"{location}.kind 类型值无效")
        if diagram["type"] == "sequence" and not isinstance(edge.get("order"), (int, float)):
            errors.append(f"{location} 时序消息必须提供数字 order")
        if edge.get("evidence") is not None and not isinstance(edge["evidence"], list):
            errors.append(f"{location}.evidence 必须是数组")

    sub_diagrams = diagram.get("subDiagrams", [])
    if not isinstance(sub_diagrams, list):
        errors.append(f"{_path}.subDiagrams 必须是数组")
        return errors
    sub_ids: set[str] = set()
    for sub in sub_diagrams:
        if not isinstance(sub, dict) or not _is_text(sub.get("id")):
            errors.append(f"{_path} 存在无效子图")
            continue
        sub_ids.add(sub["id"])
    for i, node in enumerate(nodes):
        drilldown = node.get("drilldown") if isinstance(node, dict) else None
        if drilldown and drilldown not in sub_ids:
            errors.append(f"{_path}.nodes[{i}].drilldown 未关联到子图")
    for sub in sub_diagrams:
        errors.extend(validate_diagram(sub, _path=f"{_path}/{sub.get('title', '子图')}"))

    if diagram.get("type") == "architecture" and _path == "主图":
        options = diagram.get("layout", {}) if isinstance(diagram.get("layout"), dict) else {}
        if options.get("contractVersion") != 2:
            errors.append("架构主图必须声明 layout.contractVersion=2；旧版模块连线 IR 需迁移后再使用")
        template = diagram.get("template")
        if template is None:
            pipeline_ids = {item.get("id") for item in options.get("pipelineGroups", []) if isinstance(item, dict)}
            template = ("B" if {"offline", "online"}.issubset(pipeline_ids) else
                        "C" if options.get("projectKind") == "library" else
                        "D" if options.get("deploymentZones") else "A")
        if template not in _TEMPLATES:
            errors.append("主图.template 必须是 A、B、C 或 D")
        if diagram.get("edges"):
            errors.append("新版架构主图不能用模块级 edges；真实模块关系应放到下钻图，主图使用 layerFlows")
        layer_flows = diagram.get("layerFlows")
        if not isinstance(layer_flows, list):
            errors.append("新版架构主图必须提供 layerFlows 数组；没有真实层间流向时使用空数组")
            layer_flows = []
        ordinary_layers = [layer for layer in layers if isinstance(layer, dict) and not layer.get("crossCutting")]
        ordinary_ids = [layer.get("id") for layer in ordinary_layers]
        layer_by_id = {layer.get("id"): layer for layer in layers if isinstance(layer, dict)}
        for layer in ordinary_layers:
            standard_type = layer.get("standardType")
            if standard_type not in _STANDARD_LAYER_TYPES:
                errors.append(f"新版主图层 {layer.get('id')} 必须标注 standardType")
        for layer in layers:
            if isinstance(layer, dict) and layer.get("crossCutting") and layer.get("standardType") != "governance":
                errors.append(f"横切层 {layer.get('id')} 的 standardType 必须是 governance")
        layout = options
        layer_merges = layout.get("layerMerges", [])
        if not isinstance(layer_merges, list):
            errors.append("layout.layerMerges 必须是数组")
            layer_merges = []
        if len(ordinary_layers) >= 7:
            if not isinstance(layer_merges, list) or not layer_merges:
                errors.append("普通层达到 7 层时，结构 IR 必须提供有依据的相邻层合并方案")
            else:
                merged_ids: list[str] = []
                for merge_index, merge in enumerate(layer_merges):
                    if not isinstance(merge, dict):
                        errors.append(f"layout.layerMerges[{merge_index}] 必须是对象")
                        continue
                    source_ids = merge.get("sourceLayerIds", [])
                    if (not isinstance(source_ids, list) or len(source_ids) < 2
                            or any(source_id not in ordinary_ids for source_id in source_ids)):
                        errors.append(f"layout.layerMerges[{merge_index}] 必须合并至少两个存在的普通层")
                    else:
                        positions = [ordinary_ids.index(source_id) for source_id in source_ids]
                        if positions != list(range(min(positions), max(positions) + 1)):
                            errors.append(f"layout.layerMerges[{merge_index}] 只能合并相邻层")
                        merged_ids.extend(source_ids)
                    if not _is_text(merge.get("id")) or not _is_text(merge.get("name")):
                        errors.append(f"layout.layerMerges[{merge_index}] 必须有 id 和展示名")
                    if not _is_text(merge.get("rationale")):
                        errors.append(f"layout.layerMerges[{merge_index}] 必须记录职责合并依据")
                    if not isinstance(merge.get("evidence"), list) or not merge["evidence"]:
                        errors.append(f"layout.layerMerges[{merge_index}] 必须提供证据")
                if len(merged_ids) != len(set(merged_ids)):
                    errors.append("layout.layerMerges 不能重复合并同一层")
                if len(ordinary_layers) - len(set(merged_ids)) + len(layer_merges) > 6:
                    errors.append("相邻层合并后仍超过 6 层；请重新审阅层级边界")
        visual_layer_ids = list(ordinary_ids)
        if template == "A" and isinstance(layer_merges, list):
            for merge in layer_merges:
                if not isinstance(merge, dict):
                    continue
                sources = merge.get("sourceLayerIds", [])
                if isinstance(sources, list) and sources:
                    visual_layer_ids = [layer_id for layer_id in visual_layer_ids if layer_id not in sources]
                    insert_at = min((ordinary_ids.index(source) for source in sources if source in ordinary_ids),
                                    default=len(visual_layer_ids))
                    visual_layer_ids.insert(insert_at, merge.get("id"))
        elif template == "B":
            # The renderer always places the offline lane above the online lane,
            # independent of the order used to serialize pipelineGroups.
            visual_layer_ids = ["offline", "online"]
        elif template == "C":
            groups = layout.get("kernelGroups", {})
            visual_layer_ids = [groups[key].get("id", key) for key in
                                ("publicApi", "kernel", "extensions", "tooling")
                                if isinstance(groups, dict) and isinstance(groups.get(key), dict)]
        elif template == "D":
            visual_layer_ids = [zone.get("id") for zone in layout.get("deploymentZones", [])
                                if isinstance(zone, dict)]
        if not isinstance(diagram.get("mainChain"), list):
            errors.append("新版架构主图必须提供 mainChain 数组")
        else:
            main_chain = diagram["mainChain"]
            if not main_chain:
                errors.append("mainChain 至少包含一个真实主链路模块；没有单一主链路时应先向用户澄清聚焦方式")
            if len(main_chain) > 7:
                errors.append("mainChain 最多包含 7 个模块")
            for node_id in main_chain:
                if not isinstance(node_id, str) or node_id not in node_ids:
                    errors.append(f"mainChain 引用了不存在的模块 {node_id}")
            if any(not isinstance(node_id, str) for node_id in main_chain):
                errors.append("mainChain 中的模块 ID 必须是字符串")
            elif len(main_chain) != len(set(main_chain)):
                errors.append("mainChain 不得重复引用模块")
        if len(nodes) > 25:
            errors.append("新版主图超过 25 个模块；应先形成有证据的域卡片并保留下钻，再进入布局")
        for layer in ordinary_layers:
            members = [node for node in nodes if node.get("layer") == layer.get("id")]
            if len(members) >= 11:
                groups = [node.get("group") for node in members]
                if any(not isinstance(group, str) or not group.strip() for group in groups):
                    errors.append(f"层 {layer.get('name')} 有 11 个以上模块，必须先按真实职责填写 group")
                group_names = {str(group) for group in groups if group}
                if any(len("".join(name.split())) > 4 for name in group_names):
                    errors.append(f"层 {layer.get('name')} 的 group 名称最多 4 字")
        seen_layer_pairs: set[tuple[str, str]] = set()
        adjacent_layer_pairs = set(zip(visual_layer_ids, visual_layer_ids[1:]))
        if template == "B" and len(visual_layer_ids) == 2:
            adjacent_layer_pairs.add((visual_layer_ids[1], visual_layer_ids[0]))
        if len(layer_flows) > min(8, max(0, len(visual_layer_ids) - 1)):
            errors.append("layerFlows 数量不得超过相邻层数量减一，且最多 8 条")
        for index, flow in enumerate(layer_flows):
            location = f"主图.layerFlows[{index}]"
            if not isinstance(flow, dict):
                errors.append(f"{location} 必须是对象")
                continue
            source_id, target_id = flow.get("fromLayer"), flow.get("toLayer")
            if source_id not in visual_layer_ids or target_id not in visual_layer_ids:
                errors.append(f"{location} 必须引用存在的展示泳道 ID")
            elif (source_id, target_id) not in adjacent_layer_pairs:
                errors.append(f"{location} 只能连接相邻层，且方向必须符合层级顺序")
            pair = (source_id, target_id)
            if pair in seen_layer_pairs:
                errors.append(f"{location} 与前一条重复连接同一对层")
            seen_layer_pairs.add(pair)
            label = flow.get("label", "")
            if not isinstance(label, str) or len("".join(label.split())) > 6:
                errors.append(f"{location}.label 最多 6 字")
            evidence = flow.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                errors.append(f"{location}.evidence 必须提供真实关系证据")
            elif any(not isinstance(ref, dict) or not _is_text(ref.get("path")) for ref in evidence):
                errors.append(f"{location}.evidence 必须包含有效路径")
        if len(ordinary_layers) <= 2 and template not in {"B", "C"}:
            errors.append("只有 1–2 个运行层时，必须使用双管线模板 B 或内核扩展模板 C")
        if template == "B":
            pipeline_groups = layout.get("pipelineGroups", [])
            if not isinstance(pipeline_groups, list):
                errors.append("模板 B 的 pipelineGroups 必须是数组")
                pipeline_groups = []
            pipeline_types = {item.get("id") for item in pipeline_groups if isinstance(item, dict)}
            if not {"offline", "online"}.issubset(pipeline_types):
                errors.append("模板 B 必须明确标出离线与在线两条管线")
            else:
                ordinary_node_ids = {node.get("id") for node in nodes
                                      if not layer_by_id.get(node.get("layer"), {}).get("crossCutting")}
                declared_ids = [node_id for item in pipeline_groups if isinstance(item, dict)
                                for node_id in (item.get("nodeIds") if isinstance(item.get("nodeIds"), list) else [])]
                if set(declared_ids) != ordinary_node_ids or len(declared_ids) != len(set(declared_ids)):
                    errors.append("模板 B 的两条管线 nodeIds 必须无遗漏、无重复地覆盖全部普通模块")
                for group in pipeline_groups:
                    if not isinstance(group, dict) or not _is_text(group.get("name")):
                        errors.append("模板 B 的每条管线必须有中文展示名")
                    if not isinstance(group, dict) or not isinstance(group.get("evidence"), list) or not group["evidence"]:
                        errors.append("模板 B 的每条管线必须提供证据")
                merge = layout.get("pipelineMerge")
                if isinstance(merge, dict):
                    if not isinstance(merge.get("evidence"), list) or not merge["evidence"]:
                        errors.append("模板 B 的管线汇合关系必须提供证据")
                    if merge.get("from") not in {"offline", "online"} or merge.get("to") not in {"offline", "online"} or merge.get("from") == merge.get("to"):
                        errors.append("模板 B 的汇合方向必须连接离线与在线两条不同管线")
                elif not any({flow.get("fromLayer"), flow.get("toLayer")} == {"offline", "online"}
                             for flow in layer_flows if isinstance(flow, dict)):
                    errors.append("模板 B 必须通过带证据的 layerFlows 或 pipelineMerge 表达两条管线间的汇合")
        if template == "C":
            kernel_groups = layout.get("kernelGroups", {})
            group_ids = {"publicApi", "kernel"}
            if not isinstance(kernel_groups, dict) or not group_ids.issubset(kernel_groups):
                errors.append("模板 C 必须明确提供公共 API 与内核模块；扩展和工具链按代码事实选配")
            else:
                declared_ids = [node_id for group in kernel_groups.values() if isinstance(group, dict)
                                for node_id in (group.get("nodeIds") if isinstance(group.get("nodeIds"), list) else [])]
                ordinary_node_ids = {node.get("id") for node in nodes
                                     if not layer_by_id.get(node.get("layer"), {}).get("crossCutting")}
                if set(declared_ids) != ordinary_node_ids or len(declared_ids) != len(set(declared_ids)):
                    errors.append("模板 C 的分组 nodeIds 必须无遗漏、无重复地覆盖全部普通模块")
                for group_id, group in kernel_groups.items():
                    if not isinstance(group, dict) or not _is_text(group.get("name")):
                        errors.append(f"模板 C 的 {group_id} 组必须有中文展示名")
                    elif not group.get("nodeIds"):
                        errors.append(f"模板 C 的 {group_id} 组至少包含一个模块")
                    if not isinstance(group, dict) or not isinstance(group.get("evidence"), list) or not group["evidence"]:
                        errors.append(f"模板 C 的 {group_id} 组必须提供证据")
        if template == "D":
            zones = layout.get("deploymentZones", [])
            if not isinstance(zones, list) or not zones:
                errors.append("模板 D 必须提供有证据的 deploymentZones")
            else:
                declared_ids = [node_id for zone in zones if isinstance(zone, dict)
                                for node_id in (zone.get("nodeIds") if isinstance(zone.get("nodeIds"), list) else [])]
                ordinary_node_ids = {node.get("id") for node in nodes
                                     if not layer_by_id.get(node.get("layer"), {}).get("crossCutting")}
                if set(declared_ids) != ordinary_node_ids or len(declared_ids) != len(set(declared_ids)):
                    errors.append("模板 D 的部署分区 nodeIds 必须无遗漏、无重复地覆盖全部普通模块")
                for zone_index, zone in enumerate(zones):
                    if (not isinstance(zone, dict) or not _is_text(zone.get("id"))
                            or not _is_text(zone.get("name")) or not zone.get("nodeIds")):
                        errors.append(f"模板 D 的 deploymentZones[{zone_index}] 必须有 id、名称和模块")
                    if not isinstance(zone, dict) or not isinstance(zone.get("evidence"), list) or not zone["evidence"]:
                        errors.append(f"模板 D 的 deploymentZones[{zone_index}] 必须提供证据")
    return errors


def require_valid_diagram(diagram: Any) -> dict[str, Any]:
    errors = validate_diagram(diagram)
    if errors:
        raise DiagramValidationError("\n".join(f"- {item}" for item in errors))
    return diagram
