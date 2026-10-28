"""确定性泳道、时序和正交流程布局，不依赖外部布局服务。"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from typing import Any


PAD = 36
NODE_MIN_W = 194
NODE_MAX_W = 280
NODE_BASE_H = 108
NODE_GAP_X = 36
LANE_GAP_Y = 18
ARCH_NODE_MIN_W = 200
ARCH_NODE_MAX_W = 200
ARCH_NODE_BASE_H = 68
ARCH_NODE_MAX_H = 68
ARCH_NODE_GAP_X = 16
ARCH_LANE_GAP_Y = 24
ARCH_LANE_HEADER_H = 58
ARCH_LANE_MIN_H = 130
ARCH_LANE_BOTTOM = 10
ARCH_EDGE_OUTSET = 16
ARCH_ROW_LIMIT = 5
ARCH_SIDEBAR_W = 220
FLOW_DETAIL_MAX_W = NODE_MAX_W
FLOW_DETAIL_CARD_H = 68
FLOW_DETAIL_TITLE_BASELINE = 21
FLOW_DETAIL_DESC_BASELINE = 39
FLOW_DETAIL_TAG_BASELINE = 53
FLOW_DETAIL_TAG_LINE_HEIGHT = 12

# Contract v2: fixed canvas and typography; content is adapted before font sizes.
ARCH_V2_WIDTH = 1440
ARCH_V2_OUTER_X = 24
ARCH_V2_LANE_PAD_X = 24
ARCH_V2_LANE_GAP_Y = 36
ARCH_V2_LANE_HEADER_H = 58
ARCH_V2_CARD_H = 64
ARCH_V2_CARD_GAP_X = 16
ARCH_V2_CARD_GAP_Y = 12
ARCH_V2_CARD_MIN_W = 180
ARCH_V2_GOV_GAP = 20
ARCH_V2_GOV_PAD = 16
ARCH_V2_MAIN_TOP = 84
ARCH_V2_GROUP_HEADER_H = 22
ARCH_V2_GROUP_GAP = 16


def text_width(text: str, font_size: int = 16) -> float:
    """按中日韩字符、全角标点和常见拉丁字符估算排版宽度。"""
    width = 0.0
    for char in text:
        width += font_size if ord(char) >= 0x2E80 else font_size * 0.56
    return width


def select_template(diagram: dict) -> tuple[str, str]:
    """Select a deterministic architecture template from declared project signals."""
    explicit = diagram.get("template")
    if explicit in {"A", "B", "C", "D"}:
        return explicit, "结构 IR 明确指定模板"
    options = diagram.get("layout", {}) if isinstance(diagram.get("layout"), dict) else {}
    pipelines = options.get("pipelineGroups", [])
    pipeline_ids = {item.get("id") for item in pipelines if isinstance(item, dict)}
    if {"offline", "online"}.issubset(pipeline_ids):
        return "B", "IR 明确声明离线与在线两条管线"
    if options.get("projectKind") == "library":
        return "C", "IR 标明这是库或 SDK 项目"
    if options.get("deploymentZones"):
        return "D", "IR 提供部署分区及其证据"
    return "A", "未发现双管线、库/SDK 或部署分区信号，采用默认分层泳道模板"


def wrap_text(text: str, max_width: float, font_size: int = 16) -> list[str]:
    if not text:
        return []
    lines: list[str] = []
    current = ""
    current_width = 0.0
    for char in text:
        char_width = font_size if ord(char) >= 0x2E80 else font_size * 0.56
        if current and current_width + char_width > max_width:
            lines.append(current)
            current, current_width = char, char_width
        else:
            current += char
            current_width += char_width
    if current:
        lines.append(current)
    return lines


def _fit_line(text: str, max_width: float, font_size: int) -> str:
    """将单行文本收进固定宽度，超出时用省略号表示。"""
    if text_width(text, font_size) <= max_width:
        return text
    suffix = "…"
    available = max(0, max_width - text_width(suffix, font_size))
    fitted = ""
    for char in text:
        if text_width(fitted + char, font_size) > available:
            break
        fitted += char
    return fitted + suffix


def _wrap_limited(text: str, max_width: float, font_size: int, max_lines: int) -> list[str]:
    lines = wrap_text(text, max_width, font_size)
    if len(lines) <= max_lines:
        return lines
    visible = lines[:max_lines]
    visible[-1] = _fit_line(visible[-1] + "…", max_width, font_size)
    return visible


def _wrap_detail_description(text: str, max_width: float, font_size: int = 12) -> list[str]:
    """Wrap a complete detail description into balanced lines without orphan words."""
    if not text:
        return []
    if text_width(text, font_size) <= max_width:
        return [text]

    candidates: list[tuple[float, int, int, list[str]]] = []
    for split_at in range(1, len(text)):
        first, second = text[:split_at], text[split_at:]
        if len(first.strip()) < 3 or len(second.strip()) < 3:
            continue
        first_width = text_width(first, font_size)
        second_width = text_width(second, font_size)
        if first_width > max_width or second_width > max_width:
            continue
        # Prefer a punctuation/space boundary when two splits are similarly balanced.
        boundary_penalty = 0 if first[-1].isspace() or first[-1] in "，。；：、/·—-" else 1
        candidates.append((abs(first_width - second_width), boundary_penalty, split_at, [first, second]))

    if not candidates:
        raise ValueError("下钻模块说明无法在两行内平衡排版（每行至少 3 字）：请精简说明后再布局")
    return min(candidates, key=lambda item: (item[0], item[1], item[2]))[3]


def _size_nodes(nodes: list[dict], *, compact: bool = False, architecture_root: bool = False,
                route_annotations: dict[str, list[str]] | None = None) -> dict[str, dict]:
    sizes: dict[str, dict] = {}
    route_annotations = route_annotations or {}
    for node in nodes:
        route_annotation = route_annotations.get(node["id"], [])
        if compact:
            if architecture_root:
                # Root cards render compact titles at 14px. Reserve only the
                # card's inner padding here; reserving the drill icon's full
                # width made valid 10-character Chinese titles wrap into a
                # stranded final character even though the icon sits above
                # the title baseline.
                title_width = ARCH_NODE_MIN_W - 28
                title_lines = wrap_text(node["title"], title_width, 14)
                if len(title_lines) > 2:
                    raise ValueError(f"主图模块标题超过两行：{node['id']}；请精简标题或调整结构")
                desc = node.get("desc", "")
                sizes[node["id"]] = {
                    "id": node["id"], "width": ARCH_NODE_MIN_W, "height": ARCH_NODE_MAX_H,
                    "title_lines": title_lines, "desc_lines": [desc] if desc else [],
                    "route_annotation_lines": [],
                    "saved_position": node.get("position", {}) if isinstance(node.get("position"), dict) else {},
                }
                continue
            # Detail cards preserve their complete text. The drill icon sits in
            # the card's upper-right corner, so it does not require a large
            # horizontal title reservation; width grows to keep titles on one
            # line and descriptions on at most two lines.
            title = node.get("title", "")
            desc = node.get("desc", "")
            title_width = text_width(title, 15)
            desc_width = text_width(desc, 12)
            width = max(ARCH_NODE_MIN_W, math.ceil(title_width + 48),
                        math.ceil(desc_width / 2 + 42))
            title_lines = [title] if title else []
            desc_lines = _wrap_detail_description(desc, width - 42, 12)
            if len(desc_lines) > 2:
                raise ValueError(f"下钻模块说明超过两行：{node['id']}；请精简说明后再布局")
            annotation_lines: list[str] = []
            if route_annotation:
                tags = [str(item) for item in route_annotation if str(item).strip()]
                # Keep one complete description line beside a fixed two-line
                # route-tag slot. Widen only as much as needed; card height
                # remains fixed so branch metadata does not stretch the graph.
                width = FLOW_DETAIL_MAX_W
                if desc_width + 42 > width:
                    raise ValueError(f"分支来源卡片说明放不进固定说明位：{node['id']}；请精简说明")
                width = max(width, math.ceil(desc_width + 42))
                longest_tag = max((text_width(tag, 10) for tag in tags), default=0)
                if longest_tag > width - 24:
                    raise ValueError(f"分支用途标签放不进来源卡片：{node['id']}；请精简标签或拆分关系图")
                desc_lines = _wrap_detail_description(desc, width - 42, 12)
                for tag in tags:
                    candidate = f"{annotation_lines[-1]}  ·  {tag}" if annotation_lines else tag
                    if text_width(candidate, 10) <= width - 24:
                        if annotation_lines:
                            annotation_lines[-1] = candidate
                        else:
                            annotation_lines.append(candidate)
                    else:
                        annotation_lines.append(tag)
                if len(annotation_lines) > 2:
                    raise ValueError(f"分支用途超过卡片固定标签位：{node['id']}；请精简标签或拆分关系图")
            height = ARCH_NODE_MAX_H if annotation_lines else max(58, 22 + 17 * len(title_lines) + 14 * len(desc_lines))
            if height > ARCH_NODE_MAX_H:
                raise ValueError(f"下钻模块文字无法放入紧凑卡片：{node['id']}；请精简说明后再布局")
            saved = node.get("position", {})
            sizes[node["id"]] = {
                "id": node["id"], "width": width, "height": height,
                "title_lines": title_lines, "desc_lines": desc_lines,
                "route_annotation_lines": annotation_lines,
                "saved_position": saved if isinstance(saved, dict) else {},
            }
            continue
        title_lines = wrap_text(node["title"], 222, 20)
        desc_lines = wrap_text(node.get("desc", ""), 222, 13)
        title_w = max((text_width(line, 20) for line in title_lines), default=0)
        desc_w = max((text_width(line, 13) for line in desc_lines), default=0)
        width = min(NODE_MAX_W, max(NODE_MIN_W, math.ceil(max(title_w, desc_w) + 42)))
        height = max(NODE_BASE_H, 64 + 28 * len(title_lines) + 21 * len(desc_lines))
        saved = node.get("position", {})
        sizes[node["id"]] = {
            "id": node["id"], "width": width, "height": height,
            "title_lines": title_lines, "desc_lines": desc_lines,
            "route_annotation_lines": [],
            "saved_position": saved if isinstance(saved, dict) else {},
        }
    return sizes


def _balanced_rows(members: list[dict], limit: int = 5) -> list[list[dict]]:
    if len(members) <= limit:
        return [members]
    if len(members) <= 2 * limit:
        first = (len(members) + 1) // 2
        return [members[:first], members[first:]]
    raise ValueError(f"单个职责组有 {len(members)} 个模块；请先细分职责组或制作下钻图")


def _main_chain_rank(diagram: dict) -> dict[str, int]:
    return {node_id: index for index, node_id in enumerate(diagram.get("mainChain", []))}


def _v2_member_sort_key(item: dict, chain_rank: dict[str, int]) -> tuple:
    node_id = item["id"]
    if node_id in chain_rank:
        return (0, chain_rank[node_id], node_id)
    return (1, item.get("order", 10**9), node_id)


def _v2_layer_rows(layer: dict, members: list[dict], chain_rank: dict[str, int] | None = None) -> tuple[list[dict], int]:
    """Return visual row bands and the maximum module count in any band."""
    chain_rank = chain_rank or {}
    members = sorted(members, key=lambda item: _v2_member_sort_key(item, chain_rank))
    if len(members) <= 10:
        rows = _balanced_rows(members)
        return ([{"groups": [], "rows": rows, "height": len(rows) * ARCH_V2_CARD_H
                  + max(0, len(rows) - 1) * ARCH_V2_CARD_GAP_Y}],
                max((len(row) for row in rows), default=1))

    grouped: dict[str, list[dict]] = {}
    for node in members:
        group = node.get("group")
        if not isinstance(group, str) or not group.strip():
            raise ValueError(f"层 {layer['name']} 有 11 个以上模块，但模块缺少真实职责 group")
        grouped.setdefault(group, []).append(node)

    atoms: list[dict] = []
    for group_name, group_members in grouped.items():
        if len(group_name.strip()) > 4:
            raise ValueError(f"层 {layer['name']} 的分组名“{group_name}”超过 4 字")
        group_members.sort(key=lambda item: _v2_member_sort_key(item, chain_rank))
        rows = _balanced_rows(group_members)
        atoms.append({"name": group_name, "rows": rows,
                      "columns": max((len(row) for row in rows), default=1),
                      "height": ARCH_V2_GROUP_HEADER_H + len(rows) * ARCH_V2_CARD_H
                      + max(0, len(rows) - 1) * ARCH_V2_CARD_GAP_Y + 4})

    bands: list[list[dict]] = []
    current: list[dict] = []
    current_columns = 0
    for atom in atoms:
        if current and current_columns + atom["columns"] > 5:
            bands.append(current)
            current, current_columns = [], 0
        current.append(atom)
        current_columns += atom["columns"]
    if current:
        bands.append(current)
    return ([{"groups": band,
              "height": max(atom["height"] for atom in band)} for band in bands],
            max((sum(atom["columns"] for atom in band) for band in bands), default=1))


def _v2_visual_layer_plan(diagram: dict, template: str) -> tuple[list[dict], list[dict], dict[str, str]]:
    """Resolve evidence-backed display lanes without changing source-layer facts."""
    options = diagram.get("layout", {}) if isinstance(diagram.get("layout"), dict) else {}
    source_layers = [layer for layer in diagram["layers"] if not layer.get("crossCutting")]
    cross = [layer for layer in diagram["layers"] if layer.get("crossCutting")]
    ordinary_nodes = [node for node in diagram["nodes"]
                      if not next((layer.get("crossCutting") for layer in diagram["layers"]
                                   if layer.get("id") == node.get("layer")), False)]
    nodes_by_id = {node["id"]: node for node in ordinary_nodes}
    plan: list[dict] = []
    node_lane: dict[str, str] = {}

    if template == "C":
        groups = options["kernelGroups"]
        for key in ("publicApi", "kernel", "extensions", "tooling"):
            group = groups.get(key)
            if not isinstance(group, dict) or not group.get("nodeIds"):
                continue
            lane_id = group.get("id", key)
            members = [nodes_by_id[node_id] for node_id in group["nodeIds"]]
            lane = {"id": lane_id, "name": group["name"], "desc": group.get("desc", ""),
                    "standardType": "other", "templateRole": key}
            plan.append({"layer": lane, "members": members})
            node_lane.update({node["id"]: lane_id for node in members})
    elif template == "D":
        zones = options["deploymentZones"]
        if len(zones) > 6:
            raise ValueError("模板 D 最多展示 6 个部署分区；请按有证据的网络边界归并分区")
        for zone in zones:
            members = [nodes_by_id[node_id] for node_id in zone["nodeIds"]]
            lane = {"id": zone["id"], "name": zone["name"], "desc": zone.get("desc", ""),
                    "standardType": "other", "templateRole": "deployment"}
            plan.append({"layer": lane, "members": members})
            node_lane.update({node["id"]: zone["id"] for node in members})
    else:
        merges = options.get("layerMerges", []) if template == "A" else []
        merge_at = {}
        skipped = set()
        for merge in merges:
            sources = merge["sourceLayerIds"]
            merge_at[sources[0]] = merge
            skipped.update(sources[1:])
        for source_layer in source_layers:
            if source_layer["id"] in skipped:
                continue
            merge = merge_at.get(source_layer["id"])
            if merge:
                source_ids = set(merge["sourceLayerIds"])
                lane = {"id": merge["id"], "name": merge["name"], "desc": merge.get("desc", ""),
                        "standardType": merge.get("standardType", "other"),
                        "mergeRationale": merge["rationale"]}
            else:
                source_ids = {source_layer["id"]}
                lane = dict(source_layer)
            members = [node for node in ordinary_nodes if node.get("layer") in source_ids]
            plan.append({"layer": lane, "members": members})
            node_lane.update({node["id"]: lane["id"] for node in members})

    if len(plan) > 6:
        raise ValueError("分层模板最多显示 6 条泳道；请在结构 IR 中按职责合并相邻层并记录依据")
    assigned = [node_id for item in plan for node_id in (node["id"] for node in item["members"])]
    if set(assigned) != set(nodes_by_id) or len(assigned) != len(set(assigned)):
        raise ValueError("展示泳道必须无遗漏、无重复地覆盖所有非治理模块")
    return plan, cross, node_lane


def _v2_fit_canvas_height(layout: dict) -> dict:
    natural = max(1, max((layer["y"] + layer["height"] for layer in layout.get("layers", [])), default=760) + 50)
    height = max(800, natural)
    offset = (height - natural) / 2
    if offset:
        for item in [*layout.get("layers", []), *layout.get("nodes", []), *layout.get("groupFrames", [])]:
            item["y"] += offset
        for edge in layout.get("edges", []):
            for point in edge.get("points", []):
                point["y"] += offset
            if edge.get("labelPosition"):
                edge["labelPosition"]["y"] += offset
    layout["height"] = height
    layout["legendFooterGap"] = height - max((layer["y"] + layer["height"]
                                               for layer in layout.get("layers", [])), default=0)
    return layout


def _layout_architecture_v2(diagram: dict, sizes: dict[str, dict]) -> dict:
    template, template_reason = select_template(diagram)
    if template == "B":
        return _layout_pipeline_template(diagram, sizes, template_reason)

    options = diagram.get("layout", {}) if isinstance(diagram.get("layout"), dict) else {}
    display_plan, cross, node_lane = _v2_visual_layer_plan(diagram, template)
    ordinary = [item["layer"] for item in display_plan]
    if len(cross) > 1:
        raise ValueError("横切治理侧栏最多设置一个；多个治理职责放入同一侧栏分组")
    row_specs: dict[str, list[dict]] = {}
    max_columns = 1
    members_by_lane = {item["layer"]["id"]: item["members"] for item in display_plan}
    chain_rank = _main_chain_rank(diagram)
    for layer in ordinary:
        members = members_by_lane[layer["id"]]
        if not members:
            raise ValueError(f"层 {layer['name']} 没有模块；删除空层或补全有证据的模块")
        bands, columns = _v2_layer_rows(layer, members, chain_rank)
        row_specs[layer["id"]] = bands
        max_columns = max(max_columns, columns)

    has_governance = bool(cross)
    gap_x = ARCH_V2_CARD_GAP_X
    if has_governance:
        numerator = (ARCH_V2_WIDTH - 2 * ARCH_V2_OUTER_X - ARCH_V2_GOV_GAP
                     - 2 * ARCH_V2_GOV_PAD - 2 * ARCH_V2_LANE_PAD_X
                     - gap_x * (max_columns - 1))
        card_width = math.floor(numerator / (max_columns + 1))
    else:
        content_width = ARCH_V2_WIDTH - 2 * ARCH_V2_OUTER_X - 2 * ARCH_V2_LANE_PAD_X
        card_width = math.floor((content_width - gap_x * (max_columns - 1)) / max_columns)
    if card_width < ARCH_V2_CARD_MIN_W:
        raise ValueError(f"1440px 画布下统一卡片宽度仅 {card_width}px；需减少同排模块或先分组/拆图，不得缩小字号")

    lane_width = (ARCH_V2_WIDTH - 2 * ARCH_V2_OUTER_X
                  - (ARCH_V2_GOV_GAP + card_width + 2 * ARCH_V2_GOV_PAD if has_governance else 0))
    lane_x = ARCH_V2_OUTER_X
    gap_y = ARCH_V2_LANE_GAP_Y
    y = ARCH_V2_MAIN_TOP
    lane_layouts: list[dict] = []
    positions: list[dict] = []
    group_frames: list[dict] = []
    for layer_index, layer in enumerate(ordinary):
        bands = row_specs[layer["id"]]
        layer_height = ARCH_V2_LANE_HEADER_H + 8 + sum(band["height"] for band in bands)
        layer_height += max(0, len(bands) - 1) * ARCH_V2_CARD_GAP_Y + 8
        lane = {"id": layer["id"], "name": layer["name"], "desc": layer.get("desc", ""),
                "standardType": layer.get("standardType"), "templateRole": layer.get("templateRole"),
                "pipeline": layer.get("pipeline"), "x": lane_x, "y": y,
                "width": lane_width, "height": layer_height, "crossCutting": False,
                "template": template}
        lane_layouts.append(lane)
        band_y = y + ARCH_V2_LANE_HEADER_H + 8
        for band_index, band in enumerate(bands):
            if not band["groups"]:
                for subrow_index, row in enumerate(band["rows"]):
                    count = len(row)
                    occupied = count * card_width + max(0, count - 1) * gap_x
                    start_x = lane_x + (lane_width - occupied) / 2
                    for node_index, node in enumerate(row):
                        saved = sizes[node["id"]].get("saved_position", {})
                        node_x = saved.get("x", start_x + node_index * (card_width + gap_x))
                        node_y = saved.get("y", band_y + subrow_index * (ARCH_V2_CARD_H + ARCH_V2_CARD_GAP_Y))
                        positions.append({"id": node["id"], "layer": layer["id"], "sourceLayer": node.get("layer"),
                                          "row": band_index * 10 + subrow_index,
                                          "x": node_x, "y": node_y, "width": card_width, "height": ARCH_V2_CARD_H,
                                          "title_lines": [node["title"]],
                                          "desc_lines": [node.get("desc", "")] if node.get("desc") else [],
                                          "compact": True, "bodyFontPx": 12,
                                          "chainOrder": _chain_order(diagram, node["id"])})
                band_y += band["height"] + ARCH_V2_CARD_GAP_Y
                continue

            group_widths = [atom["columns"] * card_width + max(0, atom["columns"] - 1) * gap_x
                            for atom in band["groups"]]
            occupied = sum(group_widths) + max(0, len(group_widths) - 1) * gap_x
            cursor_x = lane_x + (lane_width - occupied) / 2
            for atom_index, (atom, group_width) in enumerate(zip(band["groups"], group_widths)):
                group_height = atom["height"]
                group_frames.append({"id": f"{layer['id']}-group-{len(group_frames) + 1}",
                                     "name": atom["name"], "layer": layer["id"],
                                     "x": cursor_x, "y": band_y, "width": group_width,
                                     "height": group_height})
                rows_top = band_y + ARCH_V2_GROUP_HEADER_H
                for subrow_index, row in enumerate(atom["rows"]):
                    count = len(row)
                    row_width = count * card_width + max(0, count - 1) * gap_x
                    start_x = cursor_x + (group_width - row_width) / 2
                    for node_index, node in enumerate(row):
                        saved = sizes[node["id"]].get("saved_position", {})
                        positions.append({"id": node["id"], "layer": layer["id"], "sourceLayer": node.get("layer"),
                                          "row": band_index * 10 + subrow_index,
                                          "x": saved.get("x", start_x + node_index * (card_width + gap_x)),
                                          "y": saved.get("y", rows_top + subrow_index * (ARCH_V2_CARD_H + ARCH_V2_CARD_GAP_Y)),
                                          "width": card_width, "height": ARCH_V2_CARD_H,
                                          "title_lines": [node["title"]],
                                          "desc_lines": [node.get("desc", "")] if node.get("desc") else [],
                                          "compact": True, "bodyFontPx": 12,
                                          "chainOrder": _chain_order(diagram, node["id"])})
                cursor_x += group_width + gap_x
            band_y += band["height"] + ARCH_V2_CARD_GAP_Y
        y += layer_height + gap_y

    if cross:
        side_x = lane_x + lane_width + ARCH_V2_GOV_GAP
        first_y = lane_layouts[0]["y"] if lane_layouts else ARCH_V2_MAIN_TOP
        last_bottom = lane_layouts[-1]["y"] + lane_layouts[-1]["height"] if lane_layouts else first_y + 240
        gov_layer = cross[0]
        gov_height = max(260, last_bottom - first_y)
        gov_desc = gov_layer.get("desc", "")
        lane_layouts.append({"id": gov_layer["id"], "name": gov_layer["name"], "desc": gov_desc,
                             "crossCutting": True, "standardType": "governance",
                             "crossCuttingLabel": "贯穿所有层", "x": side_x, "y": first_y,
                             "width": card_width + 2 * ARCH_V2_GOV_PAD, "height": gov_height,
                             "template": template})
        gov_nodes = [node for node in diagram["nodes"] if node.get("layer") == gov_layer["id"]]
        header_bottom = first_y + ARCH_V2_LANE_HEADER_H + 6
        available = max(0, gov_height - (header_bottom - first_y) - 10)
        slot = available / max(1, len(gov_nodes))
        for index, node in enumerate(gov_nodes):
            node_y = header_bottom + index * slot + max(0, (slot - ARCH_V2_CARD_H) / 2)
            saved = sizes[node["id"]].get("saved_position", {})
            positions.append({"id": node["id"], "layer": gov_layer["id"], "row": index,
                              "x": saved.get("x", side_x + ARCH_V2_GOV_PAD), "y": saved.get("y", node_y),
                              "width": card_width, "height": ARCH_V2_CARD_H,
                              "title_lines": [node["title"]],
                              "desc_lines": [node.get("desc", "")] if node.get("desc") else [],
                              "compact": True, "bodyFontPx": 12,
                              "chainOrder": _chain_order(diagram, node["id"])})

    layer_by_id = {item["id"]: item for item in lane_layouts}
    ordinary_order = [item["id"] for item in lane_layouts if not item.get("crossCutting")]
    layout_edges: list[dict] = []
    ordinary_position = {layer_id: index for index, layer_id in enumerate(ordinary_order)}
    seen_layer_pairs: set[frozenset[str]] = set()
    layer_flow_label_used = False
    for flow in diagram.get("layerFlows", []):
        source = layer_by_id.get(flow.get("fromLayer"))
        target = layer_by_id.get(flow.get("toLayer"))
        if not source or not target:
            raise ValueError(f"层间通道 {flow.get('id', '<无 ID>')} 引用了不存在的泳道")
        if (source["id"] not in ordinary_position or target["id"] not in ordinary_position
                or abs(ordinary_position[source["id"]] - ordinary_position[target["id"]]) != 1):
            raise ValueError(f"层间通道 {flow.get('id', '<无 ID>')} 必须连接相邻的普通泳道")
        pair = frozenset((source["id"], target["id"]))
        if pair in seen_layer_pairs:
            raise ValueError(f"相邻泳道 {source['name']} / {target['name']} 之间最多一条层间通道")
        seen_layer_pairs.add(pair)
        center_x = source["x"] + source["width"] / 2
        points = [{"x": center_x, "y": source["y"] + source["height"]},
                  {"x": center_x, "y": target["y"]}]
        label = str(flow.get("label", "")) if not layer_flow_label_used else ""
        label_position = {"x": center_x + 18 + text_width(label, 12) / 2,
                          "y": (points[0]["y"] + points[1]["y"]) / 2 + 4} if label else None
        layer_flow_label_used = layer_flow_label_used or bool(label)
        layout_edges.append({"id": flow["id"], "from": flow["fromLayer"], "to": flow["toLayer"],
                             "label": label, "kind": "layer_flow", "main": True,
                             "async": False, "layerFlow": True, "points": points, "bends": 0,
                             "labelPosition": label_position, "evidence": flow.get("evidence", [])})

    height = (lane_layouts[-1]["y"] + lane_layouts[-1]["height"] + 50) if lane_layouts else 260
    if cross and lane_layouts:
        height = max(height, lane_layouts[-1]["y"] + lane_layouts[-1]["height"] + 50)
    return _v2_fit_canvas_height({"width": ARCH_V2_WIDTH, "height": height, "nodes": positions, "layers": lane_layouts,
                                 "edges": layout_edges, "groupFrames": group_frames, "template": template,
                                 "templateReason": template_reason, "mainChain": _main_chain_display(diagram),
                                 "hardcodedPorts": False, "contractVersion": 2})


def _chain_order(diagram: dict, node_id: str) -> int | None:
    try:
        return diagram.get("mainChain", []).index(node_id) + 1
    except ValueError:
        return None


def _main_chain_display(diagram: dict) -> list[dict]:
    by_id = {node["id"]: node for node in diagram.get("nodes", [])}
    return [{"id": node_id, "title": by_id[node_id]["title"], "number": index + 1}
            for index, node_id in enumerate(diagram.get("mainChain", [])) if node_id in by_id]


def _layout_pipeline_template(diagram: dict, sizes: dict[str, dict], template_reason: str) -> dict:
    """Lay out offline and online pipelines as two independent horizontal swimlanes."""
    options = diagram.get("layout", {})
    groups = options.get("pipelineGroups", []) if isinstance(options, dict) else []
    by_group = {item.get("id"): item for item in groups if isinstance(item, dict)}
    if not {"offline", "online"}.issubset(by_group):
        raise ValueError("模板 B 需要 layout.pipelineGroups 中的 offline 与 online 两条有证据管线")
    ordinary_nodes = [node for node in diagram["nodes"]
                      if not next((layer.get("crossCutting") for layer in diagram["layers"]
                                   if layer.get("id") == node.get("layer")), False)]
    assigned: list[dict] = []
    pipeline_rows: list[tuple[dict, list[dict]]] = []
    for key in ("offline", "online"):
        group = by_group[key]
        members = [next((node for node in ordinary_nodes if node["id"] == node_id), None)
                   for node_id in group.get("nodeIds", [])]
        if any(node is None for node in members) or not members:
            raise ValueError(f"模板 B 的 {key} 管线 nodeIds 必须引用存在的非治理模块")
        assigned.extend(members)
        pipeline_rows.append((group, _balanced_rows(members)))
    if {node["id"] for node in assigned} != {node["id"] for node in ordinary_nodes}:
        raise ValueError("模板 B 的两条管线必须且只能覆盖全部非治理模块")
    max_columns = max(len(row) for _, rows in pipeline_rows for row in rows)
    has_governance = any(layer.get("crossCutting") for layer in diagram["layers"])
    gap_x = ARCH_V2_CARD_GAP_X
    if has_governance:
        numerator = (ARCH_V2_WIDTH - 2 * ARCH_V2_OUTER_X - ARCH_V2_GOV_GAP
                     - 2 * ARCH_V2_GOV_PAD - 2 * ARCH_V2_LANE_PAD_X
                     - gap_x * (max_columns - 1))
        card_width = math.floor(numerator / (max_columns + 1))
    else:
        content_width = ARCH_V2_WIDTH - 2 * ARCH_V2_OUTER_X - 2 * ARCH_V2_LANE_PAD_X
        card_width = math.floor((content_width - gap_x * (max_columns - 1)) / max_columns)
    if card_width < ARCH_V2_CARD_MIN_W:
        raise ValueError("双管线在固定字号下放不下；请分拆管线或下钻，不得缩小字号")
    lane_width = ARCH_V2_WIDTH - 2 * ARCH_V2_OUTER_X - (
        ARCH_V2_GOV_GAP + card_width + 2 * ARCH_V2_GOV_PAD if has_governance else 0)
    y = ARCH_V2_MAIN_TOP
    lanes, positions = [], []
    pipeline_centers = {}
    for group, rows in pipeline_rows:
        lane_id = group["id"]
        row_height = len(rows) * ARCH_V2_CARD_H + max(0, len(rows) - 1) * ARCH_V2_CARD_GAP_Y
        lane_height = ARCH_V2_LANE_HEADER_H + 12 + row_height + 12
        lanes.append({"id": lane_id, "name": group["name"], "desc": "横向处理管线",
                      "standardType": "other", "x": ARCH_V2_OUTER_X, "y": y, "width": lane_width, "height": lane_height,
                      "crossCutting": False, "pipeline": lane_id, "template": "B"})
        pipeline_centers[lane_id] = {"x": ARCH_V2_OUTER_X + lane_width - 24,
                                     "bottom": y + lane_height}
        row_y = y + ARCH_V2_LANE_HEADER_H + 12
        for row_index, row in enumerate(rows):
            occupied = len(row) * card_width + max(0, len(row) - 1) * gap_x
            start_x = ARCH_V2_OUTER_X + (lane_width - occupied) / 2
            for node_index, node in enumerate(row):
                positions.append({"id": node["id"], "layer": lane_id, "sourceLayer": node.get("layer"),
                                  "row": row_index, "x": start_x + node_index * (card_width + gap_x),
                                  "y": row_y + row_index * (ARCH_V2_CARD_H + ARCH_V2_CARD_GAP_Y),
                                  "width": card_width, "height": ARCH_V2_CARD_H,
                                  "title_lines": [node["title"]],
                                  "desc_lines": [node.get("desc", "")] if node.get("desc") else [],
                                  "compact": True, "bodyFontPx": 12,
                                  "chainOrder": _chain_order(diagram, node["id"])})
        y += lane_height + ARCH_V2_LANE_GAP_Y

    edges = []
    layer_flow_label_used = False
    rendered_pairs: set[frozenset[str]] = set()
    lane_order = {lane["id"]: index for index, lane in enumerate(lanes)}
    for flow in diagram.get("layerFlows", []):
        source = next((item for item in lanes if item["id"] == flow.get("fromLayer")), None)
        target = next((item for item in lanes if item["id"] == flow.get("toLayer")), None)
        if not source or not target:
            continue
        x = source["x"] + source["width"] / 2
        if lane_order[source["id"]] < lane_order[target["id"]]:
            start_y, end_y = source["y"] + source["height"], target["y"]
        else:
            start_y, end_y = source["y"], target["y"] + target["height"]
        points = [{"x": x, "y": start_y}, {"x": x, "y": end_y}]
        label = str(flow.get("label", "")) if not layer_flow_label_used else ""
        layer_flow_label_used = layer_flow_label_used or bool(label)
        label_position = ({"x": x + 18 + text_width(label, 12) / 2,
                           "y": (points[0]["y"] + points[1]["y"]) / 2 + 4} if label else None)
        edges.append({"id": flow["id"], "from": source["id"], "to": target["id"],
                      "label": label, "kind": "layer_flow", "main": True,
                      "async": False, "layerFlow": True, "points": points, "bends": 0,
                      "labelPosition": label_position, "evidence": flow.get("evidence", [])})
        rendered_pairs.add(frozenset((source["id"], target["id"])))
    merge = options.get("pipelineMerge") if isinstance(options, dict) else None
    if isinstance(merge, dict):
        source = next((item for item in lanes if item["id"] == merge.get("from")), None)
        target = next((item for item in lanes if item["id"] == merge.get("to")), None)
        if source and target and frozenset((source["id"], target["id"])) not in rendered_pairs:
            x = source["x"] + source["width"] / 2
            if lane_order[source["id"]] < lane_order[target["id"]]:
                start_y, end_y = source["y"] + source["height"], target["y"]
            else:
                start_y, end_y = source["y"], target["y"] + target["height"]
            points = [{"x": x, "y": start_y}, {"x": x, "y": end_y}]
            merge_label = str(merge.get("label", "汇合")) if not layer_flow_label_used else ""
            layer_flow_label_used = layer_flow_label_used or bool(merge_label)
            edges.append({"id": merge.get("id", "pipeline-merge"), "from": source["id"], "to": target["id"],
                          "label": merge_label, "kind": "layer_flow", "main": True,
                          "async": False, "layerFlow": True, "points": points, "bends": 0,
                          "labelPosition": None, "evidence": merge.get("evidence", [])})
            rendered_pairs.add(frozenset((source["id"], target["id"])))
    if has_governance:
        gov = next(layer for layer in diagram["layers"] if layer.get("crossCutting"))
        side_x = ARCH_V2_OUTER_X + lane_width + ARCH_V2_GOV_GAP
        first_y, last_bottom = lanes[0]["y"], lanes[-1]["y"] + lanes[-1]["height"]
        gov_height = last_bottom - first_y
        lanes.append({"id": gov["id"], "name": gov["name"], "desc": gov.get("desc", ""),
                      "x": side_x, "y": first_y, "width": card_width + 2 * ARCH_V2_GOV_PAD,
                      "height": gov_height, "crossCutting": True, "standardType": "governance",
                      "crossCuttingLabel": "贯穿所有层", "template": "B"})
        gov_nodes = [node for node in diagram["nodes"] if node.get("layer") == gov["id"]]
        slot = max(1, gov_height - ARCH_V2_LANE_HEADER_H - 12) / max(1, len(gov_nodes))
        for index, node in enumerate(gov_nodes):
            positions.append({"id": node["id"], "layer": gov["id"], "row": index,
                              "x": side_x + ARCH_V2_GOV_PAD,
                              "y": first_y + ARCH_V2_LANE_HEADER_H + index * slot + max(0, (slot - ARCH_V2_CARD_H) / 2),
                              "width": card_width, "height": ARCH_V2_CARD_H,
                              "title_lines": [node["title"]],
                              "desc_lines": [node.get("desc", "")] if node.get("desc") else [],
                              "compact": True, "bodyFontPx": 12,
                              "chainOrder": _chain_order(diagram, node["id"])})
    height = max(item["y"] + item["height"] for item in lanes) + 50
    return _v2_fit_canvas_height({"width": ARCH_V2_WIDTH, "height": height, "nodes": positions, "layers": lanes,
                                 "edges": edges, "groupFrames": [], "template": "B", "templateReason": template_reason,
                                 "mainChain": _main_chain_display(diagram), "hardcodedPorts": False, "contractVersion": 2})


def _place_architecture_row(row: dict, sizes: dict[str, dict], lane_x: int, gap_x: int,
                            column_by_id: dict[str, int], column_widths: dict[int, int],
                            occupied_columns: list[int]) -> dict[str, float]:
    members = sorted(row["members"], key=lambda item: (item.get("order", 10**9), item["id"]))
    content_left = lane_x + 220
    column_x: dict[int, float] = {}
    cursor = content_left
    for column in occupied_columns:
        column_x[column] = cursor
        cursor += column_widths[column] + gap_x
    positions: dict[str, float] = {}
    for node in members:
        node_id = node["id"]
        column = column_by_id[node_id]
        positions[node_id] = column_x[column] + (column_widths[column] - sizes[node_id]["width"]) / 2
    return positions


def row_h_for(row: dict, sizes: dict[str, dict]) -> int:
    return max((sizes[node["id"]]["height"] for node in row["members"]), default=ARCH_NODE_BASE_H)


def _flow_edge_plan(diagram: dict) -> dict[str, Any]:
    """Classify relation edges before routing; dense bipartite meshes become matrices."""
    if diagram.get("type") != "flow":
        return {"groups": [], "annotations": {}, "matrix": None}
    nodes = {node["id"]: node for node in diagram.get("nodes", [])}
    edges = list(diagram.get("edges", []))
    outgoing: dict[str, list[dict]] = defaultdict(list)
    incoming: dict[str, list[dict]] = defaultdict(list)
    for edge in edges:
        outgoing[edge["from"]].append(edge)
        incoming[edge["to"]].append(edge)

    by_layer_pair: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for edge in edges:
        source_layer = nodes.get(edge["from"], {}).get("layer")
        target_layer = nodes.get(edge["to"], {}).get("layer")
        if source_layer != target_layer:
            by_layer_pair[(str(source_layer), str(target_layer))].append(edge)
    matrix = None
    for (source_layer, target_layer), members in sorted(by_layer_pair.items()):
        source_degree: dict[str, int] = defaultdict(int)
        target_degree: dict[str, int] = defaultdict(int)
        for edge in members:
            source_degree[edge["from"]] += 1
            target_degree[edge["to"]] += 1
        dense_sources = sorted(node_id for node_id, degree in source_degree.items() if degree >= 2)
        dense_targets = sorted(node_id for node_id, degree in target_degree.items() if degree >= 2)
        core_edges = [edge for edge in members
                      if edge["from"] in dense_sources and edge["to"] in dense_targets]
        if len(dense_sources) >= 2 and len(dense_targets) >= 2 and len(core_edges) >= 4:
            if len(members) != len(edges):
                raise ValueError("多对多关系与其他链路混在同一张图；请先拆分关系图，再将密集关系呈现为矩阵")
            matrix = {"sourceLayer": source_layer, "targetLayer": target_layer,
                      "sourceIds": sorted(source_degree, key=lambda item: (nodes[item].get("order", 10**9), item)),
                      "targetIds": sorted(target_degree, key=lambda item: (nodes[item].get("order", 10**9), item)),
                      "edgeIds": [edge["id"] for edge in members]}
            return {"groups": [], "annotations": {}, "matrix": matrix}

    groups: list[dict] = []
    grouped: set[str] = set()
    edge_by_pair: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for edge in edges:
        edge_by_pair[(edge["from"], edge["to"])].append(edge)
    handled_pairs: set[tuple[str, str]] = set()
    for (source, target), forward in sorted(edge_by_pair.items()):
        reverse_pair = (target, source)
        if source == target or reverse_pair in handled_pairs or reverse_pair not in edge_by_pair:
            continue
        reverse = edge_by_pair[reverse_pair]
        if len(forward) == 1 and len(reverse) == 1:
            members = [forward[0], reverse[0]]
            group_id = f"edge-group-{len(groups) + 1}"
            groups.append({"id": group_id, "pattern": "bidirectional",
                           "edgeIds": [edge["id"] for edge in members],
                           "forwardEdgeId": forward[0]["id"], "returnEdgeId": reverse[0]["id"]})
            grouped.update(edge["id"] for edge in members)
            handled_pairs.update({(source, target), reverse_pair})

    fan_out: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for edge in edges:
        if edge["id"] in grouped:
            continue
        source_layer = str(nodes.get(edge["from"], {}).get("layer", ""))
        target_layer = str(nodes.get(edge["to"], {}).get("layer", ""))
        fan_out[(edge["from"], target_layer)].append(edge)
    for (source_id, _), members in sorted(fan_out.items()):
        if len(members) < 2:
            continue
        group_id = f"edge-group-{len(groups) + 1}"
        groups.append({"id": group_id, "pattern": "fan_out",
                       "edgeIds": [edge["id"] for edge in members], "sourceId": source_id})
        grouped.update(edge["id"] for edge in members)

    fan_in: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for edge in edges:
        if edge["id"] in grouped:
            continue
        source_layer = str(nodes.get(edge["from"], {}).get("layer", ""))
        fan_in[(edge["to"], source_layer)].append(edge)
    for (target_id, _), members in sorted(fan_in.items()):
        if len(members) < 2:
            continue
        group_id = f"edge-group-{len(groups) + 1}"
        groups.append({"id": group_id, "pattern": "fan_in",
                       "edgeIds": [edge["id"] for edge in members], "targetId": target_id})
        grouped.update(edge["id"] for edge in members)

    for edge in edges:
        if edge["id"] in grouped:
            continue
        groups.append({"id": f"edge-group-{len(groups) + 1}", "pattern": "one_to_one",
                       "edgeIds": [edge["id"]]})

    annotations: dict[str, list[str]] = defaultdict(list)
    edge_map = {edge["id"]: edge for edge in edges}
    for group in groups:
        if group["pattern"] not in {"fan_out", "fan_in"} or len(group["edgeIds"]) < 3:
            continue
        for edge_id in group["edgeIds"]:
            edge = edge_map[edge_id]
            label = str(edge.get("label", "")).strip()
            if label:
                annotations[edge["from"]].append(label)
    rendered_annotations = {node_id: [f"→ {label}" for label in labels]
                            for node_id, labels in annotations.items()}
    return {"groups": groups, "annotations": rendered_annotations, "matrix": None}


def _layout_relation_matrix(diagram: dict, sizes: dict[str, dict], matrix_spec: dict) -> dict:
    nodes = {node["id"]: node for node in diagram["nodes"]}
    edges = {edge["id"]: edge for edge in diagram["edges"]}
    source_ids, target_ids = matrix_spec["sourceIds"], matrix_spec["targetIds"]
    row_header_width = max(180, math.ceil(max(text_width(nodes[item]["title"], 14) for item in source_ids) + 28))
    cell_width = max(160, math.ceil(max(
        [text_width(nodes[item]["title"], 14) + 28 for item in target_ids]
        + [text_width(str(edge.get("label", "")), 12) + 24 for edge in edges.values()]
    )))
    row_height, header_height = 64, 58
    x0, y0, gap = 36, 82, 0
    table_x = x0 + row_header_width
    positions = []
    for index, node_id in enumerate(source_ids):
        positions.append({"id": node_id, "layer": matrix_spec["sourceLayer"], "x": x0,
                          "y": y0 + header_height + index * row_height,
                          "width": row_header_width, "height": row_height,
                          "title_lines": [nodes[node_id]["title"]], "desc_lines": [], "compact": True,
                          "matrixRole": "row"})
    for index, node_id in enumerate(target_ids):
        positions.append({"id": node_id, "layer": matrix_spec["targetLayer"],
                          "x": table_x + index * cell_width, "y": y0,
                          "width": cell_width, "height": header_height,
                          "title_lines": [nodes[node_id]["title"]], "desc_lines": [], "compact": True,
                          "matrixRole": "column"})
    cells = []
    pair_edges: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for edge in diagram["edges"]:
        pair_edges[(edge["from"], edge["to"])].append(edge)
    for row_index, source_id in enumerate(source_ids):
        for column_index, target_id in enumerate(target_ids):
            members = pair_edges.get((source_id, target_id), [])
            cells.append({"sourceId": source_id, "targetId": target_id,
                          "edgeIds": [edge["id"] for edge in members],
                          "labels": [str(edge.get("label", "")).strip() for edge in members if str(edge.get("label", "")).strip()],
                          "x": table_x + column_index * cell_width,
                          "y": y0 + header_height + row_index * row_height,
                          "width": cell_width, "height": row_height})
    width = table_x + len(target_ids) * cell_width + 36
    height = y0 + header_height + len(source_ids) * row_height + 48
    return {"width": width, "height": height, "nodes": positions, "layers": [], "edges": [],
            "edgeGroups": [], "viewMode": "relation_matrix",
            "matrix": {**matrix_spec, "cells": cells, "rowHeaderWidth": row_header_width,
                       "cellWidth": cell_width, "rowHeight": row_height,
                       "x": table_x, "y": y0, "headerHeight": header_height}}


def _layer_channel_midpoint(source_layer: dict | None, target_layer: dict | None,
                            layers: list[dict], direction: str) -> float | None:
    """Return the midpoint of a clear, directly adjacent lane channel."""
    if not source_layer or not target_layer:
        return None
    if direction == "LR":
        start = source_layer["x"] + source_layer["width"]
        end = target_layer["x"]
        cross_start, cross_end = source_layer["y"], source_layer["y"] + source_layer["height"]
        blocked = any(
            layer.get("id") not in {source_layer.get("id"), target_layer.get("id")}
            and layer["x"] < end and layer["x"] + layer["width"] > start
            and layer["y"] < cross_end and layer["y"] + layer["height"] > cross_start
            for layer in layers
        )
    else:
        start = source_layer["y"] + source_layer["height"]
        end = target_layer["y"]
        cross_start, cross_end = source_layer["x"], source_layer["x"] + source_layer["width"]
        blocked = any(
            layer.get("id") not in {source_layer.get("id"), target_layer.get("id")}
            and layer["y"] < end and layer["y"] + layer["height"] > start
            and layer["x"] < cross_end and layer["x"] + layer["width"] > cross_start
            for layer in layers
        )
    if blocked or end <= start:
        return None
    return (start + end) / 2


def _branch_group_geometry(group: dict, edge_map: dict[str, dict], pos_by_id: dict[str, dict],
                           direction: str, layers: list[dict] | None = None
                           ) -> tuple[dict, dict[str, list[dict[str, float]]]]:
    """Return shared orthogonal bus paths and per-evidence-edge branch paths."""
    pattern = group["pattern"]
    result = dict(group)
    member_kinds = {edge_map[edge_id].get("kind", "other") for edge_id in group.get("edgeIds", [])}
    result["kind"] = next(iter(member_kinds)) if len(member_kinds) == 1 else "mixed"
    branches: dict[str, list[dict[str, float]]] = {}
    lane_by_id = {layer["id"]: layer for layer in layers or []}
    if pattern == "fan_out":
        source = pos_by_id[group["sourceId"]]
        targets = [pos_by_id[edge_map[edge_id]["to"]] for edge_id in group["edgeIds"]]
        if direction == "LR":
            source_port = {"x": source["x"] + source["width"], "y": source["y"] + source["height"] / 2}
            target_left = min(target["x"] for target in targets)
            target_layer = lane_by_id.get(targets[0].get("layer")) if targets else None
            channel_x = (_layer_channel_midpoint(lane_by_id.get(source.get("layer")), target_layer,
                                                 list(lane_by_id.values()), direction)
                         if len(group["edgeIds"]) >= 3 else None)
            bus_x = channel_x if channel_x is not None else min(target_left - 20, source_port["x"] + 24)
            ys = [target["y"] + target["height"] / 2 for target in targets]
            trunk = _compact_route([source_port, {"x": bus_x, "y": source_port["y"]},
                                    {"x": bus_x, "y": min(ys + [source_port["y"]])},
                                    {"x": bus_x, "y": max(ys + [source_port["y"]])}])
            for edge_id in group["edgeIds"]:
                target = pos_by_id[edge_map[edge_id]["to"]]
                branches[edge_id] = [{"x": bus_x, "y": target["y"] + target["height"] / 2},
                                     {"x": target["x"], "y": target["y"] + target["height"] / 2}]
            result.update({"trunkPoints": trunk, "busX": bus_x})
        else:
            source_port = {"x": source["x"] + source["width"] / 2, "y": source["y"] + source["height"]}
            target_top = min(target["y"] for target in targets)
            target_layer = lane_by_id.get(targets[0].get("layer")) if targets else None
            channel_y = (_layer_channel_midpoint(lane_by_id.get(source.get("layer")), target_layer,
                                                 list(lane_by_id.values()), direction)
                         if len(group["edgeIds"]) >= 3 else None)
            bus_y = channel_y if channel_y is not None else min(target_top - 20, source_port["y"] + 24)
            xs = [target["x"] + target["width"] / 2 for target in targets]
            trunk = _compact_route([source_port, {"x": source_port["x"], "y": bus_y},
                                    {"x": min(xs), "y": bus_y}, {"x": max(xs), "y": bus_y}])
            for edge_id in group["edgeIds"]:
                target = pos_by_id[edge_map[edge_id]["to"]]
                branches[edge_id] = [{"x": target["x"] + target["width"] / 2, "y": bus_y},
                                     {"x": target["x"] + target["width"] / 2, "y": target["y"]}]
            result.update({"trunkPoints": trunk, "busY": bus_y})
    elif pattern == "fan_in":
        target = pos_by_id[group["targetId"]]
        sources = [pos_by_id[edge_map[edge_id]["from"]] for edge_id in group["edgeIds"]]
        if direction == "LR":
            target_port = {"x": target["x"], "y": target["y"] + target["height"] / 2}
            source_right = max(source["x"] + source["width"] for source in sources)
            source_layer = lane_by_id.get(sources[0].get("layer")) if sources else None
            channel_x = (_layer_channel_midpoint(source_layer, lane_by_id.get(target.get("layer")),
                                                 list(lane_by_id.values()), direction)
                         if len(group["edgeIds"]) >= 3 else None)
            bus_x = channel_x if channel_x is not None else max(source_right + 20, target_port["x"] - 24)
            ys = [source["y"] + source["height"] / 2 for source in sources]
            target_y = target_port["y"]
            bus_points = [{"x": bus_x, "y": min(ys + [target_y])}, {"x": bus_x, "y": max(ys + [target_y])}]
            for edge_id in group["edgeIds"]:
                source = pos_by_id[edge_map[edge_id]["from"]]
                source_port = {"x": source["x"] + source["width"], "y": source["y"] + source["height"] / 2}
                branches[edge_id] = [source_port, {"x": bus_x, "y": source_port["y"]}]
            result.update({"busPoints": bus_points,
                           "targetArrowPoints": [{"x": bus_x, "y": target_y}, target_port],
                           "busX": bus_x})
        else:
            target_port = {"x": target["x"] + target["width"] / 2, "y": target["y"]}
            source_bottom = max(source["y"] + source["height"] for source in sources)
            source_layer = lane_by_id.get(sources[0].get("layer")) if sources else None
            channel_y = (_layer_channel_midpoint(source_layer, lane_by_id.get(target.get("layer")),
                                                 list(lane_by_id.values()), direction)
                         if len(group["edgeIds"]) >= 3 else None)
            bus_y = channel_y if channel_y is not None else max(source_bottom + 20, target_port["y"] - 24)
            xs = [source["x"] + source["width"] / 2 for source in sources]
            target_x = target_port["x"]
            bus_points = [{"x": min(xs + [target_x]), "y": bus_y}, {"x": max(xs + [target_x]), "y": bus_y}]
            for edge_id in group["edgeIds"]:
                source = pos_by_id[edge_map[edge_id]["from"]]
                source_port = {"x": source["x"] + source["width"] / 2, "y": source["y"] + source["height"]}
                branches[edge_id] = [source_port, {"x": source_port["x"], "y": bus_y}]
            result.update({"busPoints": bus_points,
                           "targetArrowPoints": [{"x": target_x, "y": bus_y}, target_port],
                           "busY": bus_y})
    return result, branches


def _finish_layout(diagram: dict, positions: list[dict], layers: list[dict], width: int, height: int,
                   *, hardcoded_ports: bool = False, edge_plan: dict | None = None) -> dict:
    pos_by_id = {item["id"]: item for item in positions}
    edge_layouts: list[dict] = []
    edges = list(diagram["edges"])
    if diagram["type"] == "sequence":
        edges.sort(key=lambda edge: (edge.get("order", 10**9), edge["id"]))
        return _layout_sequence(diagram, positions, layers, width, edges)
    edge_plan = edge_plan or _flow_edge_plan(diagram)
    edge_by_id = {edge["id"]: edge for edge in edges}
    group_by_edge = {edge_id: group for group in edge_plan.get("groups", [])
                     for edge_id in group.get("edgeIds", [])}
    layer_index = {item["id"]: i for i, item in enumerate(layers)}
    outgoing: dict[str, int] = defaultdict(int)
    incoming: dict[str, int] = defaultdict(int)
    for item in edges:
        outgoing[item["from"]] += 1
        incoming[item["to"]] += 1
    incoming_edges: dict[str, list[dict]] = defaultdict(list)
    for item in edges:
        incoming_edges[item["to"]].append(item)
    target_ports: dict[str, float] = {}
    for target_id, members in incoming_edges.items():
        if len(members) < 2 or target_id not in pos_by_id:
            continue
        target = pos_by_id[target_id]
        members.sort(key=lambda item: (pos_by_id[item["from"]]["y"] + pos_by_id[item["from"]]["height"] / 2, item["id"]))
        for index, item in enumerate(members):
            if diagram["type"] == "flow" and diagram.get("direction", "LR") == "LR":
                # For an expanded single-node fan-in target, align each port with
                # its source center so the connection stays a single horizontal line.
                source = pos_by_id.get(item["from"])
                source_center = source["y"] + source["height"] / 2 if source else target["y"] + target["height"] / 2
                target_ports[item["id"]] = min(target["y"] + target["height"] - 16,
                                                max(target["y"] + 16, source_center))
            else:
                target_ports[item["id"]] = target["y"] + target["height"] * (index + 1) / (len(members) + 1)
    routed_paths: list[list[dict[str, float]]] = []
    placed_label_boxes: list[dict[str, float]] = []
    edge_groups: list[dict] = []
    branch_points: dict[str, list[dict[str, float]]] = {}
    for group in edge_plan.get("groups", []):
        if group["pattern"] in {"fan_out", "fan_in"}:
            geometry, branches = _branch_group_geometry(group, edge_by_id, pos_by_id,
                                                        diagram.get("direction", "TB"), layers)
            geometry["branchPoints"] = branches
            edge_groups.append(geometry)
            branch_points.update(branches)
        elif group["pattern"] == "bidirectional":
            forward = edge_by_id[group["forwardEdgeId"]]
            reverse = edge_by_id[group["returnEdgeId"]]
            source, target = pos_by_id[forward["from"]], pos_by_id[forward["to"]]
            if diagram.get("direction", "TB") == "LR":
                center_y = source["y"] + source["height"] / 2
                source_right = source["x"] + source["width"]
                target_left = target["x"]
                track = min(12, max(8, (target_left - source_right - 32) / 4))
                mid_x = (source_right + target_left) / 2
                forward_points = _compact_route([
                    {"x": source_right, "y": center_y}, {"x": source_right + 16, "y": center_y},
                    {"x": source_right + 16, "y": center_y - track},
                    {"x": target_left - 16, "y": center_y - track},
                    {"x": target_left - 16, "y": center_y}, {"x": target_left, "y": center_y}])
                reverse_points = _compact_route([
                    {"x": target_left, "y": center_y}, {"x": target_left - 16, "y": center_y},
                    {"x": target_left - 16, "y": center_y + track},
                    {"x": source_right + 16, "y": center_y + track},
                    {"x": source_right + 16, "y": center_y}, {"x": source_right, "y": center_y}])
            else:
                center_x = source["x"] + source["width"] / 2
                source_bottom = source["y"] + source["height"]
                target_top = target["y"]
                track = min(12, max(8, (target_top - source_bottom - 32) / 4))
                mid_y = (source_bottom + target_top) / 2
                forward_points = _compact_route([
                    {"x": center_x, "y": source_bottom}, {"x": center_x, "y": source_bottom + 16},
                    {"x": center_x - track, "y": source_bottom + 16},
                    {"x": center_x - track, "y": target_top - 16},
                    {"x": center_x, "y": target_top - 16}, {"x": center_x, "y": target_top}])
                reverse_points = _compact_route([
                    {"x": center_x, "y": target_top}, {"x": center_x, "y": target_top - 16},
                    {"x": center_x + track, "y": target_top - 16},
                    {"x": center_x + track, "y": source_bottom + 16},
                    {"x": center_x, "y": source_bottom + 16}, {"x": center_x, "y": source_bottom}])
            group_points = {forward["id"]: forward_points, reverse["id"]: reverse_points}
            edge_groups.append({**group, "trackOffset": track,
                                "edgePoints": group_points, "parallel": True})
            branch_points.update(group_points)
            edge_plan.setdefault("returnEdgeIds", set()).add(reverse["id"])
        elif group["pattern"] == "one_to_one":
            edge_groups.append(dict(group))

    for edge in edges:
        source, target = pos_by_id.get(edge["from"]), pos_by_id.get(edge["to"])
        if not source or not target:
            continue
        group = group_by_edge.get(edge["id"])
        if group and group["pattern"] in {"fan_out", "fan_in", "bidirectional"}:
            points = branch_points[edge["id"]]
            label_position = None
            if len(group["edgeIds"]) <= 2 and edge.get("label"):
                if group["pattern"] in {"fan_out", "fan_in"} and diagram.get("direction", "TB") == "LR":
                    first, last = points[0], points[-1]
                    label_position = {"x": (first["x"] + last["x"]) / 2,
                                      "y": first["y"] - 10}
                elif group["pattern"] == "bidirectional":
                    center = source["y"] + source["height"] / 2
                    label_position = {"x": (points[0]["x"] + points[-1]["x"]) / 2,
                                      "y": center - 22 if edge["id"] == group["forwardEdgeId"] else center + 22}
                else:
                    label_position = _edge_label_position(edge, source, target, points, outgoing[edge["from"]],
                                                          incoming[edge["to"]], diagram,
                                                          hardcoded_ports=hardcoded_ports,
                                                          label_obstacles=positions)
            show_marker = group["pattern"] != "fan_in"
            edge_layouts.append({"id": edge["id"], "from": edge["from"], "to": edge["to"],
                                 "label": edge["label"], "kind": edge.get("kind", "other"),
                                 "main": bool(edge.get("main")), "async": bool(edge.get("async")),
                                 "points": points, "bends": max(0, len(points) - 2),
                                 "labelPosition": label_position, "groupId": group["id"],
                                 "groupPattern": group["pattern"], "showMarker": show_marker,
                                 "showLabel": len(group["edgeIds"]) <= 2,
                                 "returnEdge": edge["id"] in edge_plan.get("returnEdgeIds", set()),
                                 "evidence": edge.get("evidence", [])})
            if label_position:
                label_width = max(52, len(edge.get("label", "")) * (11 if hardcoded_ports else 15) + 18)
                placed_label_boxes.append({"x": label_position["x"] - label_width / 2,
                                           "y": label_position["y"] - 11,
                                           "width": label_width, "height": 22})
            continue
        obstacles = [node for node in positions if node["id"] not in {source["id"], target["id"]}]
        points = _route(source, target, layer_index, layer_layouts=layers,
                        diagram_type=diagram["type"], direction=diagram.get("direction", "TB"),
                        hardcoded_ports=hardcoded_ports,
                        source_degree=outgoing[edge["from"]], target_degree=incoming[edge["to"]],
                        target_port_y=target_ports.get(edge["id"]), obstacles=obstacles,
                        routed_paths=routed_paths)
        routed_paths.append(points)
        label_position = None if diagram.get("showEdgeLabels") is False else _edge_label_position(
            edge, source, target, points, outgoing[edge["from"]], incoming[edge["to"]], diagram,
            hardcoded_ports=hardcoded_ports or diagram["type"] == "architecture",
            label_obstacles=positions, placed_labels=placed_label_boxes)
        if label_position and (diagram["type"] == "architecture" or hardcoded_ports):
            label_width = max(52, len(edge["label"]) * 11 + 10)
            placed_label_boxes.append({"x": label_position["x"] - label_width / 2,
                                       "y": label_position["y"] - 11,
                                       "width": label_width, "height": 22})
        edge_layouts.append({"id": edge["id"], "from": edge["from"], "to": edge["to"],
                             "label": edge["label"], "kind": edge.get("kind", "other"),
                             "main": bool(edge.get("main")), "async": bool(edge.get("async")),
                             "points": points, "bends": max(0, len(points) - 2), "labelPosition": label_position,
                             "groupId": (group["id"] if group else None),
                             "groupPattern": (group["pattern"] if group else "one_to_one"),
                             "showMarker": True, "returnEdge": edge["id"] in edge_plan.get("returnEdgeIds", set()),
                             "evidence": edge.get("evidence", [])})
    return {"width": width, "height": height, "nodes": positions, "layers": layers, "edges": edge_layouts,
            "edgeGroups": edge_groups, "hardcodedPorts": diagram["type"] == "architecture" or hardcoded_ports}


def _route(source: dict, target: dict, layer_index: dict[str, int], *, layer_layouts=None,
           diagram_type="architecture", direction="TB", source_degree=1, target_degree=1,
           target_port_y: float | None = None, obstacles=(), routed_paths=(),
           hardcoded_ports: bool = False) -> list[dict[str, float]]:
    sx = source["x"] + source["width"] / 2
    sy = source["y"] + source["height"] / 2
    tx = target["x"] + target["width"] / 2
    ty = target["y"] + target["height"] / 2
    if diagram_type == "architecture" or hardcoded_ports:
        # Flow diagrams already declare their reading direction. Using the
        # relative node-center distance here can choose side ports for nodes
        # in adjacent top/bottom swimlanes when their columns are far apart,
        # producing a backtracking staircase. Keep ports aligned with the
        # diagram's topology instead of guessing from geometry.
        horizontal = (source.get("layer") == target.get("layer")
                      if diagram_type == "architecture" else direction == "LR")
        if horizontal:
            right = tx >= sx
            source_port = {"x": source["x"] + source["width"] if right else source["x"], "y": sy}
            target_port = {"x": target["x"] if right else target["x"] + target["width"], "y": ty}
            sign = 1 if right else -1
            source_out = {"x": source_port["x"] + sign * ARCH_EDGE_OUTSET, "y": sy}
            target_out = {"x": target_port["x"] - sign * ARCH_EDGE_OUTSET, "y": ty}
            candidates = [
                [source_port, source_out, {"x": target_out["x"], "y": source_out["y"]}, target_out, target_port],
                [source_port, source_out, {"x": source_out["x"], "y": target_out["y"]}, target_out, target_port],
            ]
        else:
            down = ty >= sy
            source_port = {"x": sx, "y": source["y"] + source["height"] if down else source["y"]}
            target_port = {"x": tx, "y": target["y"] if down else target["y"] + target["height"]}
            sign = 1 if down else -1
            source_out = {"x": sx, "y": source_port["y"] + sign * ARCH_EDGE_OUTSET}
            target_out = {"x": tx, "y": target_port["y"] - sign * ARCH_EDGE_OUTSET}
            candidates = [
                [source_port, source_out, {"x": source_out["x"], "y": target_out["y"]}, target_out, target_port],
                [source_port, source_out, {"x": target_out["x"], "y": source_out["y"]}, target_out, target_port],
            ]
        clean = [_compact_route(points) for points in candidates]
        return min(enumerate(clean), key=lambda item: (_architecture_route_score(item[1], obstacles, routed_paths), item[0]))[1]
    if abs(sx - tx) < 2:
        start = {"x": sx, "y": source["y"] + source["height"] if ty >= sy else source["y"]}
        end = {"x": tx, "y": target["y"] if ty >= sy else target["y"] + target["height"]}
        return [start, end]
    same_lane = source.get("layer") == target.get("layer")
    if same_lane:
        start_x = source["x"] + source["width"] if tx > sx else source["x"]
        end_x = target["x"] if tx > sx else target["x"] + target["width"]
        return [{"x": start_x, "y": sy}, {"x": end_x, "y": ty}]
    if diagram_type == "flow" and direction == "LR":
        if tx >= sx:
            start = {"x": source["x"] + source["width"], "y": sy}
            turn_x = target["x"]
        else:
            start = {"x": source["x"], "y": sy}
            turn_x = target["x"] + target["width"]
        port_y = target_port_y if target_degree > 1 and target_port_y is not None else ty
        if abs(sy - port_y) < 2:
            return [start, {"x": turn_x, "y": port_y}]
        return [start, {"x": turn_x, "y": sy}, {"x": turn_x, "y": port_y}]
    if diagram_type == "flow" and direction == "TB":
        if source_degree > 1:
            start = {"x": source["x"] + source["width"] if tx >= sx else source["x"], "y": sy}
            return [start, {"x": tx, "y": sy}, {"x": tx, "y": target["y"]}]
        if target_degree > 1:
            start = {"x": source["x"] + source["width"] if tx >= sx else source["x"], "y": sy}
            port_x = min(target["x"] + target["width"] - 18, max(target["x"] + 18, sx))
            return [start, {"x": port_x, "y": sy}, {"x": port_x, "y": target["y"]}]
        if abs(sx - tx) < 2:
            return [{"x": sx, "y": source["y"] + source["height"]}, {"x": tx, "y": target["y"]}]
        start = {"x": source["x"] + source["width"] if tx >= sx else source["x"], "y": sy}
        return [start, {"x": tx, "y": target["y"]}]
    # 相邻泳道从源卡片底边先横向走到目标中心，再垂直到目标顶边；
    # 横段落在泳道间隙，不横穿目标行的其它卡片。
    if ty >= sy:
        start = {"x": sx, "y": source["y"] + source["height"]}
        end = {"x": tx, "y": target["y"]}
        return [start, {"x": tx, "y": start["y"]}, end]
    start = {"x": sx, "y": source["y"]}
    end = {"x": tx, "y": target["y"] + target["height"]}
    return [start, {"x": tx, "y": start["y"]}, end]


def _compact_route(points: list[dict[str, float]]) -> list[dict[str, float]]:
    """Remove duplicate and collinear intermediate points without changing route geometry."""
    result: list[dict[str, float]] = []
    for point in points:
        if result and point == result[-1]:
            continue
        if len(result) > 1:
            before, previous = result[-2], result[-1]
            vertical_between = (before["x"] == previous["x"] == point["x"]
                                and min(before["y"], point["y"]) <= previous["y"] <= max(before["y"], point["y"]))
            horizontal_between = (before["y"] == previous["y"] == point["y"]
                                  and min(before["x"], point["x"]) <= previous["x"] <= max(before["x"], point["x"]))
            if vertical_between or horizontal_between:
                result.pop()
        result.append(point)
    return result


def _route_hits_node(a: dict, b: dict, node: dict, padding: float = 4) -> bool:
    left, right = node["x"] - padding, node["x"] + node["width"] + padding
    top, bottom = node["y"] - padding, node["y"] + node["height"] + padding
    if a["y"] == b["y"]:
        return top < a["y"] < bottom and max(min(a["x"], b["x"]), left) < min(max(a["x"], b["x"]), right)
    if a["x"] == b["x"]:
        return left < a["x"] < right and max(min(a["y"], b["y"]), top) < min(max(a["y"], b["y"]), bottom)
    return True


def _routes_cross(a: dict, b: dict, c: dict, d: dict) -> bool:
    a_horizontal, c_horizontal = a["y"] == b["y"], c["y"] == d["y"]
    if a_horizontal == c_horizontal:
        if a_horizontal and a["y"] == c["y"]:
            return max(min(a["x"], b["x"]), min(c["x"], d["x"])) < min(max(a["x"], b["x"]), max(c["x"], d["x"]))
        if not a_horizontal and a["x"] == c["x"]:
            return max(min(a["y"], b["y"]), min(c["y"], d["y"])) < min(max(a["y"], b["y"]), max(c["y"], d["y"]))
        return False
    horizontal_a, horizontal_b, vertical_a, vertical_b = (a, b, c, d) if a_horizontal else (c, d, a, b)
    return (min(horizontal_a["x"], horizontal_b["x"]) < vertical_a["x"] < max(horizontal_a["x"], horizontal_b["x"])
            and min(vertical_a["y"], vertical_b["y"]) < horizontal_a["y"] < max(vertical_a["y"], vertical_b["y"]))


def _architecture_route_score(points: list[dict], obstacles, routed_paths) -> float:
    score = max(0, len(points) - 2) * 28
    for a, b in zip(points, points[1:]):
        score += (abs(a["x"] - b["x"]) + abs(a["y"] - b["y"])) * 0.04
        score += sum(100000 for node in obstacles if _route_hits_node(a, b, node))
        for route in routed_paths:
            for c, d in zip(route, route[1:]):
                if _routes_cross(a, b, c, d):
                    score += 260
                elif a["y"] == b["y"] == c["y"] == d["y"]:
                    overlap = min(max(a["x"], b["x"]), max(c["x"], d["x"])) - max(min(a["x"], b["x"]), min(c["x"], d["x"]))
                    if overlap > 8:
                        score += min(180, overlap * 2)
                elif a["x"] == b["x"] == c["x"] == d["x"]:
                    overlap = min(max(a["y"], b["y"]), max(c["y"], d["y"])) - max(min(a["y"], b["y"]), min(c["y"], d["y"]))
                    if overlap > 8:
                        score += min(180, overlap * 2)
    return score
def _edge_label_position(edge: dict, source: dict, target: dict, points: list[dict],
                         source_degree: int, target_degree: int, diagram: dict,
                         *, hardcoded_ports: bool = False, label_obstacles=(),
                         placed_labels=()) -> dict[str, float] | None:
    if edge.get("kind") == "governance" or len(points) < 2:
        return None
    if hardcoded_ports:
        label_width = max(52, len(edge["label"]) * 11 + 10)
        horizontal_first = diagram.get("direction") == "TB"
        horizontal_segments = sorted(
            ((a, b) for a, b in zip(points, points[1:])
             if a["y"] == b["y"] and abs(a["x"] - b["x"]) >= label_width + 8),
            key=lambda pair: abs(pair[0]["x"] - pair[1]["x"]), reverse=True,
        )
        vertical_segments = sorted(
            ((a, b) for a, b in zip(points, points[1:])
             if a["x"] == b["x"] and abs(a["y"] - b["y"]) >= 30),
            key=lambda pair: abs(pair[0]["y"] - pair[1]["y"]), reverse=True,
        )
        candidates: list[dict[str, float]] = []
        for horizontal in ((horizontal_segments, vertical_segments) if horizontal_first
                           else (vertical_segments, horizontal_segments)):
            for a, b in horizontal:
                if a["y"] == b["y"]:
                    candidates.append({"x": (a["x"] + b["x"]) / 2, "y": a["y"] - 10})
                else:
                    midpoint_y = (a["y"] + b["y"]) / 2
                    # Put the label over the vertical route with its white
                    # backing masking the line. This keeps the label attached
                    # to the edge and avoids the old detached side placement.
                    candidates.append({"x": a["x"], "y": midpoint_y})
        def collides(center: dict[str, float]) -> bool:
            # Match the SVG label background at label_y - 13; the old -11
            # collision box admitted labels that touched or covered cards.
            box = {"x": center["x"] - label_width / 2, "y": center["y"] - 13,
                   "width": label_width, "height": 22}
            for item in (*label_obstacles, *placed_labels):
                if (box["x"] < item["x"] + item["width"] and box["x"] + box["width"] > item["x"]
                        and box["y"] < item["y"] + item["height"] and box["y"] + box["height"] > item["y"]):
                    return True
            return False
        valid = next((candidate for candidate in candidates if not collides(candidate)), None)
        if valid:
            return valid
        if candidates:
            return candidates[0]
        return {"x": (points[0]["x"] + points[-1]["x"]) / 2, "y": (points[0]["y"] + points[-1]["y"]) / 2 - 10}
    if diagram["type"] == "architecture":
        label_width = max(52, len(edge["label"]) * 11 + 10)
        if source.get("layer") == target.get("layer"):
            horizontal = [pair for pair in zip(points, points[1:]) if pair[0]["y"] == pair[1]["y"]]
            if horizontal:
                a, b = max(horizontal, key=lambda pair: abs(pair[0]["x"] - pair[1]["x"]))
                return {"x": (a["x"] + b["x"]) / 2, "y": (a["y"] + b["y"]) / 2 - 10}
            return {"x": (points[0]["x"] + points[-1]["x"]) / 2, "y": source["y"] - 10}
        vertical = next(((a, b) for a, b in zip(points, points[1:]) if a["x"] == b["x"]), None)
        if vertical:
            a, b = vertical
            x = a["x"] + label_width / 2 + 6 if target["x"] >= source["x"] else a["x"] - label_width / 2 - 6
            return {"x": x, "y": (a["y"] + b["y"]) / 2}
        a, b = max(zip(points, points[1:]), key=lambda pair: abs(pair[0]["x"] - pair[1]["x"]))
        return {"x": (a["x"] + b["x"]) / 2, "y": (a["y"] + b["y"]) / 2 - 10}
    if diagram["type"] == "flow" and diagram.get("direction") == "LR":
        label_half = max(26, len(edge["label"]) * 7.5 + 9)
        if source_degree > 1:
            return {"x": target["x"] - label_half - 10, "y": target["y"] + target["height"] / 2 - 2}
        if target_degree > 1:
            return {"x": source["x"] + source["width"] + label_half + 10, "y": source["y"] + source["height"] / 2 - 2}
    if diagram["type"] == "flow" and diagram.get("direction") == "TB":
        if source_degree > 1:
            return {"x": target["x"] + target["width"] / 2, "y": target["y"] - 17}
        if target_degree > 1:
            return {"x": source["x"] + source["width"] / 2, "y": source["y"] + source["height"] + 18}
    a, b = max(zip(points, points[1:]), key=lambda pair: abs(pair[0]["x"] - pair[1]["x"]) + abs(pair[0]["y"] - pair[1]["y"]))
    return {"x": (a["x"] + b["x"]) / 2, "y": (a["y"] + b["y"]) / 2 - (10 if a["y"] == b["y"] else 2)}


def _flow_depths(diagram: dict, ignored_edge_ids: set[str] | None = None) -> dict[str, int]:
    ids = [node["id"] for node in diagram["nodes"]]
    outgoing: dict[str, list[str]] = defaultdict(list)
    indegree = {item: 0 for item in ids}
    for edge in diagram["edges"]:
        if edge["id"] in (ignored_edge_ids or set()):
            continue
        if edge["to"] not in outgoing[edge["from"]]:
            outgoing[edge["from"]].append(edge["to"])
            indegree[edge["to"]] += 1
    queue = deque(sorted((item for item, degree in indegree.items() if degree == 0)))
    depth = {item: 0 for item in ids}
    visited: set[str] = set()
    while queue:
        current = queue.popleft()
        visited.add(current)
        for target in sorted(outgoing[current]):
            depth[target] = max(depth[target], depth[current] + 1)
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    cycle_depth = max(depth.values(), default=0) + 1
    for item in ids:
        if item not in visited and indegree[item] > 0:
            depth[item] = max(depth[item], cycle_depth)
    return depth


def _layout_flow(diagram: dict, sizes: dict[str, dict], *, hardcoded_ports: bool = False,
                 edge_plan: dict | None = None) -> dict:
    edge_plan = edge_plan or _flow_edge_plan(diagram)
    if edge_plan.get("matrix"):
        return _layout_relation_matrix(diagram, sizes, edge_plan["matrix"])
    ignored = {group["returnEdgeId"] for group in edge_plan.get("groups", [])
               if group.get("pattern") == "bidirectional"}
    depth = _flow_depths(diagram, ignored)
    ordered_layers = diagram.get("layers", [])
    layer_rank = {layer["id"]: i for i, layer in enumerate(ordered_layers)}
    node_layer_ids = {node.get("layer") for node in diagram["nodes"]}
    # A flow detail whose nodes all belong to one architecture layer still
    # needs its own topological columns. Treating that shared layer as a single
    # layout column makes every edge route back through the same nodes.
    use_semantic_layers = bool(ordered_layers) and len(node_layer_ids) > 1
    if use_semantic_layers and all(node.get("layer") in layer_rank for node in diagram["nodes"]):
        proposed = {node["id"]: layer_rank[node["layer"]] for node in diagram["nodes"]}
        if all(proposed[edge["to"]] >= proposed[edge["from"]] for edge in diagram["edges"]):
            depth = proposed
        else:
            ordered_layers = []
    else:
        ordered_layers = []
    direction = diagram.get("direction", "LR")
    groups: dict[int, list[dict]] = defaultdict(list)
    for node in diagram["nodes"]:
        groups[depth[node["id"]]].append(node)
    if hardcoded_ports:
        # Architecture drilldowns use a consistent card size within each
        # topological swimlane. Text fitting is computed before sizing and a
        # larger peer card only adds whitespace; it never clips a shorter one.
        for members in groups.values():
            layer_width = max((sizes[node["id"]]["width"] for node in members), default=ARCH_NODE_MIN_W)
            layer_height = max((sizes[node["id"]]["height"] for node in members), default=58)
            for node in members:
                sizes[node["id"]]["width"] = layer_width
                sizes[node["id"]]["height"] = layer_height
    group_count = max(groups, default=0) + 1
    max_w = max((sizes[node["id"]]["width"] for node in diagram["nodes"]), default=NODE_MIN_W)
    max_h = max((sizes[node["id"]]["height"] for node in diagram["nodes"]), default=NODE_BASE_H)
    # Reserve a stable label bay between topology columns. A nominal 108px gap
    # makes long Chinese labels collide with the target card on fan-in routes.
    label_scale = 11 if hardcoded_ports else 15
    label_base = 14 if hardcoded_ports else 24
    label_bay = max((max(52, text_width(str(edge.get("label", "")), label_scale) + label_base)
                     for edge in diagram.get("edges", [])
                     if len(next((group["edgeIds"] for group in edge_plan.get("groups", [])
                                  if edge["id"] in group.get("edgeIds", [])), [])) <= 2), default=52)
    # Leave a measured label width plus a compact 20px visual margin between
    # one-to-one cards. Branch groups with three or more edges keep labels on
    # their source card and therefore do not inflate this channel.
    step_x = max_w + (max(100, label_bay + 20) if hardcoded_ports else max(180, label_bay + 24))
    step_y = max_h + (92 if hardcoded_ports else 126)
    flow_node_gap_x = 24 if hardcoded_ports else NODE_GAP_X
    flow_stack_gap_y = 32 if hardcoded_ports else 48
    nodes_out = []
    layers_out = []
    row_widths = [sum(sizes[node["id"]]["width"] for node in groups[level]) + max(0, len(groups[level]) - 1) * flow_node_gap_x
                  for level in range(group_count)]
    max_row_width = max(row_widths, default=max_w)
    stack_heights = [sum(sizes[node["id"]]["height"] for node in groups[level]) + max(0, len(groups[level]) - 1) * flow_stack_gap_y
                     for level in range(group_count)]
    max_stack_height = max(stack_heights, default=max_h)
    expanded_targets: dict[str, int] = {}
    if direction == "LR":
        incoming_by_id: dict[str, list[dict]] = defaultdict(list)
        for edge in diagram["edges"]:
            incoming_by_id[edge["to"]].append(edge)
        for level, members in groups.items():
            if len(members) != 1:
                continue
            target = members[0]
            inbound = incoming_by_id.get(target["id"], [])
            if len(inbound) < 2:
                continue
            source_levels = {depth[edge["from"]] for edge in inbound}
            if len(source_levels) == 1:
                source_level = next(iter(source_levels))
                if source_level < level:
                    expanded_targets[target["id"]] = source_level
    for level in range(group_count):
        members = sorted(groups[level], key=lambda node: (node.get("order", 10**9), node["id"]))
        layer = ordered_layers[level] if level < len(ordered_layers) else {"id": str(level), "name": f"第{level + 1}步"}
        if direction == "LR":
            lane_y = 64
            lane_header = 62 if hardcoded_ports else 74
            lane_h = max(190 if hardcoded_ports else 220,
                         max_stack_height + (84 if hardcoded_ports else 96))
            cursor_y = lane_y + lane_header + (max_stack_height - stack_heights[level]) / 2
            if len(members) == 1 and members[0]["id"] in expanded_targets:
                source_level = expanded_targets[members[0]["id"]]
                cursor_y = lane_y + lane_header + (max_stack_height - stack_heights[source_level]) / 2
            for index, node in enumerate(members):
                size = sizes[node["id"]]
                source_level = expanded_targets.get(node["id"])
                # Fan-in targets align to the source stack's center, but must
                # keep their own compact card height rather than stretching.
                node_height = (size["height"] if hardcoded_ports or source_level is None
                               else stack_heights[source_level])
                nodes_out.append({"id": node["id"], "layer": layer["id"], "x": 48 + level * step_x,
                                 "y": cursor_y, "width": max_w, "height": node_height,
                                 "title_lines": size["title_lines"], "desc_lines": size["desc_lines"],
                                 "routeAnnotationLines": size.get("route_annotation_lines", []),
                                 "compact": hardcoded_ports})
                cursor_y += node_height + flow_stack_gap_y
            layers_out.append({"id": layer["id"], "name": layer["name"], "desc": layer.get("desc", ""), "x": 28 + level * step_x,
                               "y": lane_y, "width": step_x - 24, "height": lane_h,
                               "crossCutting": False})
        else:
            total_w = row_widths[level]
            lane_y = 56 + level * step_y
            lane_w = max(900, max_row_width + 96)
            cursor_x = 48 + (lane_w - 96 - total_w) / 2
            for node in members:
                size = sizes[node["id"]]
                detail_header = 56 if hardcoded_ports else 64
                nodes_out.append({"id": node["id"], "layer": layer["id"], "x": cursor_x,
                                 "y": lane_y + detail_header, "width": size["width"], "height": size["height"],
                                 "title_lines": size["title_lines"], "desc_lines": size["desc_lines"],
                                 "routeAnnotationLines": size.get("route_annotation_lines", []),
                                 "compact": hardcoded_ports})
                cursor_x += size["width"] + flow_node_gap_x
            layers_out.append({"id": layer["id"], "name": layer["name"], "desc": layer.get("desc", ""), "x": 28,
                               "y": lane_y, "width": lane_w,
                               "height": max_h + (74 if hardcoded_ports else 98), "crossCutting": False})
    width = max(900, 36 + group_count * step_x) if direction == "LR" else max(900, 56 + max(900, max_row_width + 96))
    # Reserve a stable footer for the relationship legend rendered in every
    # flow detail. Keep it outside the swimlanes and edge-label area.
    height = max(330, (64 + max(220, max_stack_height + 96) + 28) if direction == "LR" else 56 + group_count * step_y) + 42
    return _finish_layout(diagram, nodes_out, layers_out, width, height,
                          hardcoded_ports=hardcoded_ports, edge_plan=edge_plan)


def _layout_sequence(diagram: dict, sizes: dict[str, dict], layers: list[dict], width: int, edges: list[dict]) -> dict:
    participants = diagram["nodes"]
    columns = max(1, len(participants))
    max_card_width = max((sizes[node["id"]]["width"] for node in participants), default=NODE_MIN_W)
    width = max(820, columns * 230 + 90, columns * max_card_width + 2 * PAD)
    positions: list[dict] = []
    for index, node in enumerate(participants):
        size = sizes[node["id"]]
        center = (PAD + max_card_width / 2 + index * (width - 2 * PAD - max_card_width) / (columns - 1)
                  if columns > 1 else width / 2)
        positions.append({"id": node["id"], "layer": "sequence", "x": center - size["width"] / 2,
                          "y": 72, "width": size["width"], "height": 60,
                          "title_lines": size["title_lines"], "desc_lines": []})
    centers = {item["id"]: item["x"] + item["width"] / 2 for item in positions}
    messages = []
    for index, edge in enumerate(edges):
        y = 166 + index * 72
        start_x, end_x = centers[edge["from"]], centers[edge["to"]]
        if start_x == end_x:
            points = [{"x": start_x, "y": y}, {"x": start_x + 56, "y": y},
                      {"x": start_x + 56, "y": y + 30}, {"x": start_x, "y": y + 30}]
        else:
            points = [{"x": start_x, "y": y}, {"x": end_x, "y": y}]
        messages.append({"id": edge["id"], "from": edge["from"], "to": edge["to"], "label": edge["label"],
                         "kind": edge.get("kind", "message"), "main": bool(edge.get("main")),
                         "async": bool(edge.get("async")), "points": points, "bends": max(0, len(points) - 2),
                         "order": edge.get("order", index)})
    # The extra footer keeps the line-style legend below the last message and
    # gives sequence lifelines a clear stopping point above it.
    return {"width": width, "height": max(280, 190 + len(edges) * 72) + 42, "nodes": positions,
            "layers": [], "edges": messages, "lifelines": centers}


def layout_diagram(diagram: dict, *, backend: str = "auto", hardcoded_ports: bool = False) -> dict:
    edge_plan = _flow_edge_plan(diagram)
    if edge_plan.get("matrix"):
        return _layout_relation_matrix(diagram, {}, edge_plan["matrix"])
    sizes = _size_nodes(diagram["nodes"], compact=diagram["type"] == "architecture" or hardcoded_ports,
                        architecture_root=diagram["type"] == "architecture",
                        route_annotations=edge_plan.get("annotations"))
    if diagram["type"] == "sequence":
        edges = sorted(diagram["edges"], key=lambda edge: (edge.get("order", 10**9), edge["id"]))
        result = _layout_sequence(diagram, sizes, [], 900, edges)
        result["backend"] = "deterministic-sequence"
        return result
    if diagram["type"] == "architecture":
        layout_options = diagram.get("layout", {})
        if not isinstance(layout_options, dict) or layout_options.get("contractVersion") != 2:
            raise ValueError("V2 架构主图必须声明 layout.contractVersion=2；请先迁移到泳道通道结构")
        return _layout_architecture_v2(diagram, sizes)
    if backend not in {"auto", "builtin", "elkjs"}:
        raise ValueError("layout backend 必须是 auto、builtin 或 elkjs")
    # Architecture drilldown flows share the deterministic port router; ELK's
    # flow routes are intentionally bypassed only for those nested views.
    if backend in {"auto", "elkjs"} and not hardcoded_ports:
        from .elkjs_backend import available, layout_with_elkjs
        if available():
            try:
                result = layout_with_elkjs(diagram, sizes)
                if result:
                    result["backend"] = "elkjs-layered"
                    return result
            except Exception as exc:
                if backend == "elkjs":
                    raise RuntimeError(f"ELKJS 后端失败：{exc}") from exc
                warning = f"ELKJS 后端失败，已回退内置布局：{exc}"
            else:
                warning = "ELKJS 未返回布局，已回退内置布局"
        elif backend == "elkjs":
            raise RuntimeError("未找到 Node.js 或 elkjs 模块；参考 docs/layout-backends.md 配置可选 ELKJS")
        else:
            warning = "未发现可选 ELKJS，使用内置确定性布局"
    else:
        warning = None
    result = _layout_flow(diagram, sizes, hardcoded_ports=hardcoded_ports, edge_plan=edge_plan)
    result["backend"] = "builtin-layered-fixed-ports" if hardcoded_ports else "builtin-layered"
    if warning:
        result["backend_warning"] = warning
    return result
