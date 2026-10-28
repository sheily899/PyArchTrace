"""布局几何检查：画布边界、重叠、基线、正交折点、连线交叉与文字尺寸。"""

from __future__ import annotations

from itertools import combinations
import re
import xml.etree.ElementTree as ET

from .layout import (FLOW_DETAIL_CARD_H, FLOW_DETAIL_DESC_BASELINE,
                     FLOW_DETAIL_TAG_BASELINE, FLOW_DETAIL_TAG_LINE_HEIGHT,
                     FLOW_DETAIL_TITLE_BASELINE, _flow_edge_plan,
                     _layer_channel_midpoint, text_width)
from .render import _detail_legend_specs, _layer_style, render_svg


def content_density_report(
    diagram: dict,
    layout: dict,
    *,
    analysis: dict | None = None,
    sub_layouts: dict[str, dict] | None = None,
) -> dict:
    """审计信息密度、证据和可读性硬约束，并单独列出软约束警告。"""
    errors: list[dict] = []
    warnings: list[dict] = []
    graph_reports: list[dict] = []
    sub_layouts = sub_layouts or {}

    def check_graph(graph: dict, graph_layout: dict, *, root: bool, architecture_context: bool) -> None:
        graph_id = graph.get("id", "unknown")
        nodes = graph.get("nodes", [])
        contract_v2 = (graph.get("type") == "architecture"
                       and isinstance(graph.get("layout"), dict)
                       and graph["layout"].get("contractVersion") == 2
                       and graph_layout.get("contractVersion") == 2)
        edges = list(graph_layout.get("edges", [])) if root and contract_v2 else list(graph.get("edges", []))
        line_legend_required = not (root and graph.get("type") == "architecture" and contract_v2)
        legend_specs = _detail_legend_specs(graph, graph_layout) if line_legend_required else []
        legend_svg = render_svg(graph, graph_layout) if line_legend_required else ""
        missing_legend_styles = [
            str(item["key"]) for item in legend_specs
            if f'data-legend-key="{item["key"]}"' not in legend_svg
        ]
        if missing_legend_styles:
            errors.append({"code": "line_style_legend_missing", "graph": graph_id,
                           "styles": missing_legend_styles,
                           "message": "图中实际使用的线型或边框样式必须在图例中解释"})
        per_layer: dict[str, list[dict]] = {}
        positions = {item.get("id"): item for item in graph_layout.get("nodes", [])}
        uniform_layers = architecture_context and graph.get("type") != "sequence"
        visual_layers = (graph_layout.get("layers", []) if root and contract_v2 else graph.get("layers", []))
        cross_cutting_layer_ids = {layer.get("id") for layer in visual_layers if layer.get("crossCutting")}
        for layer in visual_layers:
            if layer.get("id") is not None:
                per_layer.setdefault(str(layer["id"]), [])
        missing_positions = sorted((node.get("id") for node in nodes if node.get("id") not in positions), key=str)
        if missing_positions:
            errors.append({"code": "node_layout_missing", "graph": graph_id, "nodes": missing_positions,
                           "message": "布局必须为每个图中模块提供位置"})
        if root and contract_v2:
            chain_ids = set(graph.get("mainChain", []))
            for node in nodes:
                details = node.get("details", {}) if isinstance(node.get("details"), dict) else {}
                has_declared_relation = bool(details.get("depends_on") or details.get("used_by"))
                if node.get("id") not in chain_ids and not node.get("drilldown") and not has_declared_relation:
                    warnings.append({"code": "module_without_visible_relation", "graph": graph_id,
                                     "node": node.get("id"),
                                     "message": "模块不在主链路、无下钻入口且未声明依赖关系；请确认是否应上图"})
        for node in nodes:
            position = positions.get(node.get("id"), {})
            if not root and graph.get("type") == "flow" and architecture_context:
                title_lines = position.get("title_lines", [])
                desc_lines = position.get("desc_lines", [])
                if title_lines != [node.get("title", "")]:
                    errors.append({"code": "drilldown_title_wrapped", "graph": graph_id,
                                   "node": node.get("id"), "message": "下钻卡片名必须完整单行显示"})
                if "".join(desc_lines) != str(node.get("desc", "")) or any(
                    "…" in str(line) or "..." in str(line) for line in desc_lines
                ):
                    errors.append({"code": "drilldown_description_truncated", "graph": graph_id,
                                   "node": node.get("id"), "message": "下钻说明必须完整显示，不得省略截断"})
                if len(desc_lines) > 2:
                    errors.append({"code": "drilldown_description_too_many_lines", "graph": graph_id,
                                   "node": node.get("id"), "message": "下钻说明最多显示两行"})
                if any(len(str(line).strip()) < 3 for line in desc_lines):
                    errors.append({"code": "drilldown_description_orphan_line", "graph": graph_id,
                                   "node": node.get("id"), "message": "下钻说明每行至少 3 字，不得出现孤行"})
            visual_layer_id = position.get("layer", node.get("layer", "sequence")) if contract_v2 and root else node.get("layer", "sequence")
            per_layer.setdefault(str(visual_layer_id), []).append(node)
            if not isinstance(node.get("evidence"), list) or not node["evidence"] or any(
                not isinstance(ref, dict) or not isinstance(ref.get("path"), str) or not ref["path"].strip()
                for ref in node.get("evidence", [])
            ):
                errors.append({"code": "node_evidence_missing", "graph": graph_id, "node": node.get("id"),
                               "message": "每个模块都必须有证据路径"})
            if analysis is not None:
                details = node.get("details")
                required = {"summary", "responsibilities", "inputs", "outputs", "depends_on", "used_by",
                            "key_files", "tech", "confidence"}
                if not isinstance(details, dict) or not required.issubset(details):
                    errors.append({"code": "module_details_incomplete", "graph": graph_id, "node": node.get("id"),
                                   "message": "模块详情必须包含 summary、responsibilities、inputs、outputs、depends_on、used_by、key_files、tech、confidence"})
                else:
                    if not isinstance(details.get("summary"), str) or not details["summary"].strip():
                        errors.append({"code": "module_summary_missing", "graph": graph_id, "node": node.get("id"),
                                       "message": "模块详情 summary 必须为非空文本"})
                    responsibilities = details.get("responsibilities")
                    if not isinstance(responsibilities, list) or len(responsibilities) > 4:
                        errors.append({"code": "module_responsibilities_invalid", "graph": graph_id, "node": node.get("id"),
                                       "message": "模块详情 responsibilities 最多 4 条"})
                    for field in ("inputs", "outputs", "depends_on", "used_by", "key_files", "tech"):
                        if not isinstance(details.get(field), list):
                            errors.append({"code": "module_detail_list_invalid", "graph": graph_id, "node": node.get("id"),
                                           "field": field, "message": f"模块详情 {field} 必须为数组"})
                    confidence = details.get("confidence")
                    if not isinstance(confidence, dict) or any(not isinstance(confidence.get(field), list)
                                                                for field in ("evidence", "inference", "pending")):
                        errors.append({"code": "module_confidence_invalid", "graph": graph_id, "node": node.get("id"),
                                       "message": "confidence 必须包含 evidence、inference、pending 三个数组"})

        layer_reports = []
        for layer_id, members in per_layer.items():
            count = len(members)
            cross_cutting = layer_id in cross_cutting_layer_ids
            layer_positions = [positions[node["id"]] for node in members if node.get("id") in positions]
            dimensions = {(item.get("width"), item.get("height")) for item in layer_positions}
            if uniform_layers and len(dimensions) > 1:
                errors.append({"code": "layer_dimensions_mismatch", "graph": graph_id, "layer": layer_id,
                               "message": "同层模块必须等宽等高"})
            rows: dict[int, list[dict]] = {}
            for item in layer_positions:
                rows.setdefault(int(item.get("row", 0)), []).append(item)
            vertical_flow = graph.get("type") == "flow" and graph.get("direction") == "LR"
            if uniform_layers and not cross_cutting and not vertical_flow and any(len(row_items) > 5 for row_items in rows.values()):
                errors.append({"code": "layer_row_overflow", "graph": graph_id, "layer": layer_id,
                               "message": "同一排最多放置 5 个模块；请换行或拆分下钻图"})
            if uniform_layers and not cross_cutting:
                if vertical_flow:
                    ordered = sorted(layer_positions, key=lambda item: item["y"])
                    gaps = [round(b["y"] - (a["y"] + a["height"]), 1) for a, b in zip(ordered, ordered[1:])]
                    if len({round(item["x"], 1) for item in ordered}) > 1:
                        errors.append({"code": "layer_baseline_mismatch", "graph": graph_id, "layer": layer_id,
                                       "message": "同层纵向分支模块必须沿列对齐"})
                    if len(set(gaps)) > 1:
                        errors.append({"code": "layer_spacing_mismatch", "graph": graph_id, "layer": layer_id,
                                       "message": "同层纵向分支间距必须一致"})
                    if any(gap < 16 for gap in gaps):
                        errors.append({"code": "layer_spacing_too_small", "graph": graph_id, "layer": layer_id,
                                       "message": "同层模块间距不得小于 16px"})
                else:
                    for row_number, row_items in rows.items():
                        ordered = sorted(row_items, key=lambda item: item["x"])
                        gaps = [round(b["x"] - (a["x"] + a["width"]), 1) for a, b in zip(ordered, ordered[1:])]
                        if len(set(gaps)) > 1:
                            errors.append({"code": "layer_spacing_mismatch", "graph": graph_id, "layer": layer_id,
                                           "row": row_number, "message": "同层同排模块间距必须一致"})
                        if any(gap < 16 for gap in gaps):
                            errors.append({"code": "layer_spacing_too_small", "graph": graph_id, "layer": layer_id,
                                           "row": row_number, "message": "同层模块间距不得小于 16px"})
                        if len({round(item["y"], 1) for item in row_items}) > 1:
                            errors.append({"code": "layer_baseline_mismatch", "graph": graph_id, "layer": layer_id,
                                           "row": row_number, "message": "同层同排模块必须对齐"})
            if root and graph.get("type") == "architecture" and not cross_cutting:
                if count < 3:
                    warnings.append({"code": "layer_below_target", "graph": graph_id, "layer": layer_id,
                                     "moduleCount": count, "message": "该层少于 3 个模块；请说明职责单一或项目结构原因"})
                elif count > 5:
                    warnings.append({"code": "layer_above_target", "graph": graph_id, "layer": layer_id,
                                     "moduleCount": count, "message": "该层超过 5 个模块；建议按真实职责分组或下钻"})
            layer_reports.append({"layerId": layer_id, "moduleCount": count,
                                  "withinTarget": cross_cutting or 3 <= count <= 5,
                                  "uniformSize": len(dimensions) <= 1,
                                  "crossCutting": cross_cutting})

        overlong = []
        if root and graph.get("type") == "architecture":
            if contract_v2 and graph_layout.get("width") != 1440:
                errors.append({"code": "canvas_width_not_fixed", "graph": graph_id,
                               "width": graph_layout.get("width"),
                               "message": "新版架构图画布宽度必须固定为 1440px"})
            contrast_failures = _contrast_failures(graph_layout) if contract_v2 else []
            if contrast_failures:
                errors.append({"code": "contrast_below_wcag_aa", "graph": graph_id,
                               "elements": contrast_failures, "message": "文字与背景对比度低于 4.5:1"})
            for node in nodes:
                desc = "".join(str(node.get("desc", "")).split())
                if len(desc) > 12 or "…" in desc or "..." in desc:
                    overlong.append({"id": node.get("id"), "characters": len(desc), "desc": node.get("desc", "")})
                    errors.append({"code": "main_description_too_long", "graph": graph_id, "node": node.get("id"),
                                   "characters": len(desc), "message": "主图说明必须不超过 12 字，且不得使用省略号"})
                node_layout = positions.get(node.get("id"))
                if node_layout and text_width(str(node.get("desc", "")), 12) > node_layout.get("width", 0) - 28:
                    errors.append({"code": "main_description_overflows_card", "graph": graph_id,
                                   "node": node.get("id"), "message": "主图说明无法在卡片内完整显示，需改写而不是截断"})
            count = len(nodes)
            exception = None
            if analysis:
                density = analysis.get("stageB", {}).get("densityReview", {})
                exception = density.get("mainGraphException") if isinstance(density, dict) else None
            if count < 12:
                has_exception = isinstance(exception, dict) and bool(str(exception.get("reason", "")).strip()) and bool(exception.get("evidence"))
                if has_exception:
                    warnings.append({"code": "main_module_count_exception", "graph": graph_id,
                                     "moduleCount": count, "reason": exception["reason"],
                                     "message": "证据不足导致主图少于 12 个模块；已记录例外"})
                else:
                    errors.append({"code": "main_module_count_below_minimum", "graph": graph_id, "moduleCount": count,
                                   "message": "主图模块数少于 12，需有证据支持的例外说明"})
            if count > 25:
                errors.append({"code": "main_module_count_above_maximum", "graph": graph_id, "moduleCount": count,
                               "message": "主图模块数超过 25；应拆分主图范围，不得合并职责凑数"})
            if len(edges) > 8:
                errors.append({"code": "main_edge_count_above_maximum", "graph": graph_id, "edgeCount": len(edges),
                               "message": "主图连线不得超过 8 条"})
            if graph.get("showEdgeLabels") is not False:
                errors.append({"code": "main_edge_labels_enabled", "graph": graph_id,
                               "message": "主图不得显示连线标签"})
            ordered_layer_ids = [layer.get("id") for layer in
                                 (graph_layout.get("layers", []) if contract_v2 else graph.get("layers", []))
                                 if not layer.get("crossCutting")]
            layer_rank = {layer_id: index for index, layer_id in enumerate(ordered_layer_ids)}
            for edge in edges:
                if contract_v2 and edge.get("layerFlow"):
                    source_id, target_id = edge.get("from"), edge.get("to")
                    if str(edge.get("label", "")).strip() and len("".join(str(edge["label"]).split())) > 6:
                        errors.append({"code": "layer_flow_label_too_long", "graph": graph_id,
                                       "edge": edge.get("id"), "message": "层间通道标签最多 6 字"})
                    if source_id not in layer_rank or target_id not in layer_rank:
                        errors.append({"code": "layer_flow_endpoint_invalid", "graph": graph_id,
                                       "edge": edge.get("id"), "message": "层间通道端点必须是普通泳道"})
                    elif layer_rank[target_id] != layer_rank[source_id] + 1:
                        errors.append({"code": "layer_flow_not_adjacent", "graph": graph_id,
                                       "edge": edge.get("id"), "message": "主图只允许连接相邻层"})
                    continue
                source = next((node for node in nodes if node.get("id") == edge.get("from")), None)
                target = next((node for node in nodes if node.get("id") == edge.get("to")), None)
                if str(edge.get("label", "")).strip() and not (contract_v2 and edge.get("layerFlow")):
                    errors.append({"code": "main_edge_label", "graph": graph_id, "edge": edge.get("id"),
                                   "message": "主图连线不得显示标签"})
                if not source or not target or source.get("layer") == target.get("layer"):
                    errors.append({"code": "main_edge_not_layer_flow", "graph": graph_id, "edge": edge.get("id"),
                                   "message": "主图只允许层与层之间的主流向"})
                if not edge.get("main", False):
                    errors.append({"code": "main_edge_not_primary", "graph": graph_id, "edge": edge.get("id"),
                                   "message": "主图连线必须标记为层间主流向"})
                if (source and target and source.get("layer") in layer_rank and target.get("layer") in layer_rank
                        and layer_rank[source["layer"]] > layer_rank[target["layer"]]):
                    warnings.append({"code": "reverse_layer_dependency", "graph": graph_id,
                                     "edge": edge.get("id"), "fromLayer": source.get("layer"),
                                     "toLayer": target.get("layer"),
                                     "message": "下层依赖上层；请确认这是有证据的真实反向调用"})
            if contract_v2:
                main_chain = graph.get("mainChain", [])
                if not isinstance(main_chain, list) or not 1 <= len(main_chain) <= 7:
                    errors.append({"code": "main_chain_invalid", "graph": graph_id,
                                   "message": "顶部主链路必须包含 1 至 7 个模块"})
                elif any(node_id not in {node.get("id") for node in nodes} for node_id in main_chain):
                    errors.append({"code": "main_chain_node_missing", "graph": graph_id,
                                   "message": "主链路引用了图中不存在的模块"})
                for layer in graph.get("layers", []):
                    if layer.get("crossCutting"):
                        if layer.get("standardType") != "governance":
                            errors.append({"code": "crosscut_type_missing", "graph": graph_id,
                                           "layer": layer.get("id"), "message": "治理侧栏必须映射到 governance 标准层类型"})
                        if not any("贯穿所有层" in str(value) for value in
                                   (layer.get("name", ""), layer.get("desc", ""),
                                    next((placed.get("crossCuttingLabel", "") for placed in graph_layout.get("layers", [])
                                          if placed.get("id") == layer.get("id")), ""))):
                            errors.append({"code": "crosscut_marker_missing", "graph": graph_id,
                                           "layer": layer.get("id"), "message": "治理侧栏须明确标注‘贯穿所有层’"})
                card_widths = {item.get("width") for item in graph_layout.get("nodes", [])}
                if len(card_widths) > 1:
                    errors.append({"code": "global_card_width_mismatch", "graph": graph_id,
                                   "message": "全图所有模块卡片必须等宽"})
                if graph.get("mainChain"):
                    badge_violations = []
                    for item in graph_layout.get("nodes", []):
                        if not item.get("chainOrder"):
                            continue
                        source = next((node for node in nodes if node.get("id") == item.get("id")), {})
                        title_width = text_width(str(source.get("title", "")), 14)
                        title_left = item["x"] + (item["width"] - title_width) / 2
                        badge_box = {"x": item["x"] - 9, "y": item["y"] - 9, "width": 18, "height": 18}
                        title_box = {"x": title_left, "y": item["y"] + 15,
                                     "width": title_width, "height": 20}
                        if badge_box["x"] < 0 or badge_box["y"] < 0 or _overlap(badge_box, title_box):
                            badge_violations.append(item["id"])
                    svg_markup = render_svg(graph, graph_layout)
                    rendered_badges = svg_markup.count('class="chain-badge"')
                    if badge_violations or rendered_badges != len(graph.get("mainChain", [])):
                        errors.append({"code": "chain_badge_overlap", "graph": graph_id,
                                       "nodes": badge_violations,
                                       "expected": len(graph.get("mainChain", [])), "rendered": rendered_badges,
                                       "message": "主链路编号徽标必须位于卡片外沿且不得压住标题"})
                layer_flow_labels = [edge for edge in graph_layout.get("edges", [])
                                     if edge.get("layerFlow") and str(edge.get("label", "")).strip()]
                if len(layer_flow_labels) > 1:
                    errors.append({"code": "duplicate_layer_flow_labels", "graph": graph_id,
                                   "count": len(layer_flow_labels),
                                   "message": "层间主流向含义只标注一次，其余由图例说明"})
                if graph_layout.get("legendFooterGap", 10**9) < 45:
                    errors.append({"code": "legend_footer_gap", "graph": graph_id,
                                   "gapPx": graph_layout.get("legendFooterGap"),
                                   "message": "图例与泳道底边至少保留 45px"})
                crosscut_count = sum(bool(layer.get("crossCutting")) for layer in graph.get("layers", []))
                if crosscut_count:
                    phrase_count = render_svg(graph, graph_layout).count("贯穿所有层")
                    if phrase_count != crosscut_count:
                        errors.append({"code": "crosscut_label_duplicate", "graph": graph_id,
                                       "expected": crosscut_count, "rendered": phrase_count,
                                       "message": "治理侧栏的‘贯穿所有层’标记必须且只能出现一次"})
                for node in nodes:
                    title_length = len("".join(str(node.get("title", "")).split()))
                    if title_length > 10:
                        errors.append({"code": "main_title_too_long", "graph": graph_id,
                                       "node": node.get("id"), "characters": title_length,
                                       "message": "主图卡片名最多 10 字"})
                if len(graph.get("layers", [])) and len([layer for layer in graph.get("layers", [])
                                                         if not layer.get("crossCutting")]) >= 7:
                    warnings.append({"code": "layer_count_above_template_target", "graph": graph_id,
                                     "message": "普通层达到 7 层；需依据职责合并相邻层并记录依据"})
            width = graph_layout.get("width", 0)
            if width > 1600:
                errors.append({"code": "main_canvas_too_wide", "graph": graph_id, "width": width,
                               "message": "主图渲染宽度不得超过 1600px"})
            if width > 1440:
                errors.append({"code": "main_canvas_not_readable_at_1440", "graph": graph_id, "width": width,
                               "message": "主图在 1440px 窗口下需要缩放或横向滚动；请缩短布局而不是缩小字号"})

        for edge in edges:
            evidence = edge.get("evidence")
            if not isinstance(evidence, list) or not evidence or any(
                not isinstance(ref, dict) or not isinstance(ref.get("path"), str) or not ref["path"].strip()
                for ref in evidence
            ):
                errors.append({"code": "edge_evidence_missing", "graph": graph_id, "edge": edge.get("id"),
                               "message": "每条关系（包括下钻图）都必须有证据路径"})

        if not root and graph.get("type") != "sequence" and len(edges) > 8:
            errors.append({"code": "drilldown_edge_count_above_maximum", "graph": graph_id,
                           "edgeCount": len(edges), "message": "流程/关系下钻图超过 8 条边，必须拆图"})
        if not root and not 3 <= len(nodes) <= 8:
            warnings.append({"code": "drilldown_node_count_outside_target", "graph": graph_id,
                             "nodeCount": len(nodes), "message": "下钻图建议包含 3 至 8 个模块"})
        if graph.get("type") == "sequence" and len(edges) > 12:
            warnings.append({"code": "sequence_message_count_above_target", "graph": graph_id,
                             "messageCount": len(edges), "message": "时序消息超过 12 条，建议拆分"})

        minimum_font = min((int(item.get("bodyFontPx", 12 if item.get("compact") else 13))
                            for item in positions.values()), default=12)
        hard_checks = {
            "nodeEvidenceComplete": not any(item.get("code") == "node_evidence_missing" and item.get("graph") == graph_id for item in errors),
            "nodeLayoutComplete": not any(item.get("code") == "node_layout_missing" and item.get("graph") == graph_id for item in errors),
            "edgeEvidenceComplete": not any(item.get("code") == "edge_evidence_missing" and item.get("graph") == graph_id for item in errors),
            "layerDimensionsUniform": not any(item.get("code") == "layer_dimensions_mismatch" and item.get("graph") == graph_id for item in errors),
            "layerSpacingUniform": not any(item.get("code") in {"layer_spacing_mismatch", "layer_spacing_too_small"} and item.get("graph") == graph_id for item in errors),
            "layerBaselineAligned": not any(item.get("code") == "layer_baseline_mismatch" and item.get("graph") == graph_id for item in errors),
            "atMostFiveNodesPerRow": not any(item.get("code") == "layer_row_overflow" and item.get("graph") == graph_id for item in errors),
            "minimumBodyFontAtLeast12px": minimum_font >= 12,
        }
        if line_legend_required:
            hard_checks["lineStylesExplained"] = not missing_legend_styles
        if not root and graph.get("type") == "flow" and architecture_context:
            hard_checks.update({
                "detailTitlesSingleLine": not any(
                    item.get("code") == "drilldown_title_wrapped" and item.get("graph") == graph_id
                    for item in errors
                ),
                "detailDescriptionsComplete": not any(
                    item.get("code") == "drilldown_description_truncated" and item.get("graph") == graph_id
                    for item in errors
                ),
                "detailDescriptionsAtMostTwoLines": not any(
                    item.get("code") == "drilldown_description_too_many_lines" and item.get("graph") == graph_id
                    for item in errors
                ),
            })
        aspect_ratio = (graph_layout.get("width", 0) / graph_layout.get("height", 1)
                        if graph_layout.get("height") else 0)
        if root and graph.get("type") == "architecture":
            hard_checks.update({
                "mainModuleCountInRange": 12 <= len(nodes) <= 25,
                "mainModuleCountEvidenceExceptionRecorded": any(
                    item.get("code") == "main_module_count_exception" and item.get("graph") == graph_id for item in warnings
                ),
                "mainModuleCountAccepted": 12 <= len(nodes) <= 25 or any(
                    item.get("code") == "main_module_count_exception" and item.get("graph") == graph_id for item in warnings
                ),
                "mainDescriptionsAtMost12": not overlong,
                "mainDescriptionsFitCards": not any(item.get("code") == "main_description_overflows_card" and item.get("graph") == graph_id for item in errors),
                "mainEdgeCountAtMost8": len(edges) <= 8,
                "mainEdgesAreInterLayer": not any(item.get("code") in {"main_edge_not_layer_flow", "main_edge_not_primary", "layer_flow_endpoint_invalid", "layer_flow_not_adjacent"} and item.get("graph") == graph_id for item in errors),
                "mainEdgeLabelsHidden": graph.get("showEdgeLabels") is False and not any(
                    item.get("code") in {"main_edge_labels_enabled", "main_edge_label"} and item.get("graph") == graph_id for item in errors
                ),
                "canvasWidthAtMost1600px": graph_layout.get("width", 0) <= 1600,
                "readableAt1440WithoutScaling": graph_layout.get("width", 0) <= 1440,
                "canvasWidthExactly1440px": not contract_v2 or graph_layout.get("width") == 1440,
                "aspectRatioInRange": not contract_v2 or 1.2 <= aspect_ratio <= 1.8,
                "contrastAtLeast4_5To1": not contract_v2 or not any(
                    item.get("code") == "contrast_below_wcag_aa" and item.get("graph") == graph_id for item in errors
                ),
                "mainChainAtMost7": not contract_v2 or len(graph.get("mainChain", [])) <= 7,
            })
        else:
            hard_checks["flowEdgeCountAtMost8"] = graph.get("type") == "sequence" or len(edges) <= 8
        graph_reports.append({"id": graph_id, "type": graph.get("type"), "root": root,
                              "template": graph.get("template", graph_layout.get("template")),
                              "moduleCount": len(nodes), "edgeCount": len(edges), "layers": layer_reports,
                              "overlongDescriptions": overlong,
                              "lineLegendEntries": [{"key": item["key"], "label": item["label"]}
                                                    for item in legend_specs],
                              "lineStylesExplained": not missing_legend_styles,
                              "canvasWidth": graph_layout.get("width"), "minimumBodyFontPx": minimum_font,
                              "hardChecks": hard_checks,
                              "readableAt1440WithoutScaling": graph_layout.get("width", 0) <= 1440})
        for child in graph.get("subDiagrams", []):
            child_layout = sub_layouts.get(child.get("id"))
            if child_layout is None:
                errors.append({"code": "subdiagram_layout_missing", "graph": child.get("id"),
                               "message": "下钻图未生成布局，无法完成内容审计"})
                continue
            check_graph(child, child_layout, root=False,
                        architecture_context=architecture_context or graph.get("type") == "architecture")

    check_graph(diagram, layout, root=True, architecture_context=diagram.get("type") == "architecture")
    return {"passed": not errors, "mainGraph": graph_reports[0] if graph_reports else {},
            "graphs": graph_reports, "errors": errors, "warnings": warnings}


def _overlap(a: dict, b: dict, padding: float = 0) -> bool:
    return (a["x"] < b["x"] + b["width"] + padding and a["x"] + a["width"] + padding > b["x"]
            and a["y"] < b["y"] + b["height"] + padding and a["y"] + a["height"] + padding > b["y"])


def _segment_intersection(a: dict, b: dict, c: dict, d: dict) -> bool:
    a_h = a["y"] == b["y"]
    c_h = c["y"] == d["y"]
    if a_h == c_h:
        if a_h:
            return a["y"] == c["y"] and max(min(a["x"], b["x"]), min(c["x"], d["x"])) < min(max(a["x"], b["x"]), max(c["x"], d["x"]))
        return a["x"] == c["x"] and max(min(a["y"], b["y"]), min(c["y"], d["y"])) < min(max(a["y"], b["y"]), max(c["y"], d["y"]))
    h1, h2, v1, v2 = (a, b, c, d) if a_h else (c, d, a, b)
    return (min(h1["x"], h2["x"]) < v1["x"] < max(h1["x"], h2["x"])
            and min(v1["y"], v2["y"]) < h1["y"] < max(v1["y"], v2["y"]))


def _arrow_marker_errors(svg: str) -> list[dict]:
    namespace = "{http://www.w3.org/2000/svg}"
    root = ET.fromstring(svg)
    markers = {item.get("id"): item for item in root.iter(f"{namespace}marker")}
    errors: list[dict] = []
    for marker_id, marker in markers.items():
        shape = marker.find(f"{namespace}path")
        main = str(marker_id).startswith("arrow-main-")
        length, height = (18, 14) if main else (12, 10)
        expected = (f"0 0 {length} {height}", str(length), str(height),
                    "0", f"M 0 0 L {length} {height / 2:g} L 0 {height} Z")
        actual = (marker.get("viewBox"), marker.get("markerWidth"), marker.get("markerHeight"),
                  marker.get("refX"), shape.get("d") if shape is not None else None)
        if marker.get("markerUnits") != "userSpaceOnUse" or actual != expected:
            errors.append({"marker": marker_id, "reason": "arrowhead_geometry_does_not_match_visual_class"})

    for group in root.iter(f"{namespace}g"):
        edge_line = group.find(f"{namespace}path[@class='edge-line']")
        if edge_line is None:
            continue
        reference = edge_line.get("marker-end", "")
        marker_id = reference.removeprefix("url(#").removesuffix(")")
        if (group.get("data-kind") == "governance"
                and group.get("data-show-marker") != "false" and not reference):
            errors.append({"marker": marker_id, "reason": "governance_relation_requires_arrowhead"})
        if reference and edge_line.get("stroke-linecap") != "butt":
            errors.append({"marker": marker_id, "reason": "arrow_shaft_must_stop_at_its_endpoint"})
        expected_main = group.get("data-layer-flow") == "true"
        if reference and bool(marker_id.startswith("arrow-main-")) != expected_main:
            errors.append({"marker": marker_id, "reason": "marker_visual_class_does_not_match_edge_role"})
    for path in root.iter(f"{namespace}path"):
        if path.get("class") != "edge-group-line" or path.get("data-kind") != "governance":
            continue
        if (path.get("stroke", "").upper() != "#D4A24C"
                or path.get("stroke-dasharray") != "5 5"):
            errors.append({"group": path.get("data-edge-group"),
                           "reason": "governance_group_line_style_mismatch"})
    for path in root.iter(f"{namespace}path"):
        if (path.get("data-marker-size") == "main"
                and not path.get("marker-end", "").startswith("url(#arrow-main-")):
            errors.append({"marker": path.get("marker-end"), "reason": "main_legend_requires_main_arrowhead"})
    for path in root.iter(f"{namespace}path"):
        reference = path.get("marker-end")
        if not reference:
            continue
        marker_id = reference.removeprefix("url(#").removesuffix(")")
        marker = markers.get(marker_id)
        shape = marker.find(f"{namespace}path") if marker is not None else None
        line_color = path.get("stroke", "").upper()
        arrow_color = shape.get("fill", "").upper() if shape is not None else ""
        if marker is None or not line_color or line_color != arrow_color:
            errors.append({"marker": marker_id, "reason": "arrow_color_must_match_line_color"})
        main = marker_id.startswith("arrow-main-")
        expected_length = 18 if main else 12
        shaft_x, shaft_y = path.get("data-arrow-shaft-x"), path.get("data-arrow-shaft-y")
        tip_x, tip_y = path.get("data-arrow-tip-x"), path.get("data-arrow-tip-y")
        numbers = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", path.get("d", ""))]
        match = re.search(r"(?:^|\s)L\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*$", path.get("d", ""))
        if not all(value is not None for value in (shaft_x, shaft_y, tip_x, tip_y)) or match is None:
            errors.append({"marker": marker_id, "reason": "arrow_shaft_must_end_at_head_base"})
        else:
            base = (float(shaft_x), float(shaft_y))
            tip = (float(tip_x), float(tip_y))
            endpoint = (float(match.group(1)), float(match.group(2)))
            distance = ((tip[0] - base[0]) ** 2 + (tip[1] - base[1]) ** 2) ** 0.5
            if (abs(endpoint[0] - base[0]) > 0.11 or abs(endpoint[1] - base[1]) > 0.11
                    or abs(distance - expected_length) > 0.11):
                errors.append({"marker": marker_id, "reason": "arrow_shaft_must_end_at_head_base"})
            if len(numbers) < 4:
                errors.append({"marker": marker_id, "reason": "arrow_head_must_continue_from_shaft"})
            else:
                previous = (numbers[-4], numbers[-3])
                shaft_vector = (base[0] - previous[0], base[1] - previous[1])
                head_vector = (tip[0] - base[0], tip[1] - base[1])
                cross = shaft_vector[0] * head_vector[1] - shaft_vector[1] * head_vector[0]
                dot = shaft_vector[0] * head_vector[0] + shaft_vector[1] * head_vector[1]
                if abs(cross) > 0.11 or dot <= 0:
                    errors.append({"marker": marker_id, "reason": "arrow_head_must_continue_from_shaft"})
    return errors


def quality_report(diagram: dict, layout: dict, *, hardcoded_ports: bool = False) -> dict:
    issues: list[dict] = []
    contract_v2 = (diagram.get("type") == "architecture"
                   and isinstance(diagram.get("layout"), dict)
                   and diagram["layout"].get("contractVersion") == 2
                   and layout.get("contractVersion") == 2)
    if diagram.get("type") == "architecture" and not contract_v2:
        issues.append({"code": "architecture_contract_missing",
                       "message": "架构主图必须使用 V2 泳道通道布局，旧版模块连线布局不通过审计"})
    nodes = layout.get("nodes", [])
    node_map = {node["id"]: node for node in nodes}
    diagram_nodes = {node["id"]: node for node in diagram["nodes"]}
    branch_group_violations: list[str] = []
    label_distance_violations: list[str] = []
    route_annotation_slot_violations: list[str] = []
    grouped_routes: list[tuple[str, set[str], list[dict]]] = []
    visible_arrow_count = sum(bool(edge.get("showMarker", True)) for edge in layout.get("edges", []))
    arrow_errors: list[dict] = []
    if diagram.get("type") != "architecture" or contract_v2:
        try:
            arrow_errors = _arrow_marker_errors(render_svg(diagram, layout))
        except (ValueError, ET.ParseError) as exc:
            arrow_errors = [{"reason": "rendered_svg_not_auditable", "detail": str(exc)}]
        if arrow_errors:
            issues.append({"code": "arrow_marker_invalid", "details": arrow_errors,
                           "message": "主图与其他图必须使用各自固定尺寸的实心箭头，箭头颜色须与连线一致"})

    def point_segment_distance(point: dict, first: dict, second: dict) -> float:
        dx, dy = second["x"] - first["x"], second["y"] - first["y"]
        length2 = dx * dx + dy * dy
        if not length2:
            return ((point["x"] - first["x"]) ** 2 + (point["y"] - first["y"]) ** 2) ** 0.5
        ratio = max(0, min(1, ((point["x"] - first["x"]) * dx +
                               (point["y"] - first["y"]) * dy) / length2))
        projected = {"x": first["x"] + ratio * dx, "y": first["y"] + ratio * dy}
        return ((point["x"] - projected["x"]) ** 2 + (point["y"] - projected["y"]) ** 2) ** 0.5

    if diagram.get("type") == "flow" and hardcoded_ports:
        expected = _flow_edge_plan(diagram)
        if expected.get("matrix"):
            cells = layout.get("matrix", {}).get("cells", [])
            represented = [edge_id for cell in cells for edge_id in cell.get("edgeIds", [])]
            if layout.get("viewMode") != "relation_matrix" or sorted(represented) != sorted(expected["matrix"]["edgeIds"]):
                branch_group_violations.append("many_to_many_matrix_coverage")
        else:
            expected_groups = {(item["pattern"], frozenset(item["edgeIds"])) for item in expected.get("groups", [])}
            actual_groups = {(item.get("pattern"), frozenset(item.get("edgeIds", [])))
                             for item in layout.get("edgeGroups", [])}
            if expected_groups != actual_groups:
                branch_group_violations.append("edge_group_classification")
            edge_map = {edge["id"]: edge for edge in layout.get("edges", [])}
            source_nodes = {node["id"]: node for node in layout.get("nodes", [])}
            lane_by_id = {lane["id"]: lane for lane in layout.get("layers", [])}
            direction = diagram.get("direction", "TB")
            bus_axis = "x" if direction == "LR" else "y"
            bus_key = "busX" if direction == "LR" else "busY"

            def check_bus_channel(group: dict, source_layer_id: str | None,
                                  target_layer_id: str | None, pattern: str) -> None:
                if len(group.get("edgeIds", [])) < 3:
                    return
                expected_bus = _layer_channel_midpoint(lane_by_id.get(source_layer_id),
                                                       lane_by_id.get(target_layer_id),
                                                       list(lane_by_id.values()), direction)
                if expected_bus is None:
                    return
                branch_points = group.get("branchPoints", {})
                expected_branch_xs = []
                for edge_id in group.get("edgeIds", []):
                    points = branch_points.get(edge_id, [])
                    if not points:
                        expected_branch_xs.append(False)
                    else:
                        junction = points[0] if pattern == "fan_out" else points[-1]
                        expected_branch_xs.append(abs(junction[bus_axis] - expected_bus) <= 1e-6)
                trunk = (group.get("trunkPoints", []) if pattern == "fan_out"
                         else group.get("busPoints", []))
                trunk_uses_channel = any(abs(point[bus_axis] - expected_bus) <= 1e-6 for point in trunk)
                if (abs(float(group.get(bus_key, float("inf"))) - expected_bus) > 1e-6
                        or not trunk_uses_channel or not all(expected_branch_xs)):
                    branch_group_violations.append(f'{group["id"]}:{pattern}_bus_outside_channel')

            def check_branches_reach_bus(group: dict, pattern: str) -> None:
                bus_value = float(group.get(bus_key, float("nan")))
                bus_axis_key = "x" if direction == "LR" else "y"
                branch_axis_key = "y" if direction == "LR" else "x"
                route = (group.get("trunkPoints", []) if pattern == "fan_out"
                         else group.get("busPoints", []))
                branches = group.get("branchPoints", {})
                for edge_id in group.get("edgeIds", []):
                    points = branches.get(edge_id, [])
                    if not points:
                        branch_group_violations.append(f'{group["id"]}:{pattern}_branch_disconnected')
                        continue
                    junction = points[0] if pattern == "fan_out" else points[-1]
                    coordinate = junction[branch_axis_key]
                    connected = any(
                        first[bus_axis_key] == second[bus_axis_key] == bus_value
                        and min(first[branch_axis_key], second[branch_axis_key]) <= coordinate
                        <= max(first[branch_axis_key], second[branch_axis_key])
                        for first, second in zip(route, route[1:])
                    )
                    if not connected:
                        branch_group_violations.append(f'{group["id"]}:{pattern}_branch_disconnected')

            for group in layout.get("edgeGroups", []):
                members = [edge_map.get(edge_id) for edge_id in group.get("edgeIds", [])]
                members = [edge for edge in members if edge]
                if group.get("pattern") == "fan_out":
                    source = source_nodes.get(group.get("sourceId"))
                    targets = [source_nodes.get(edge.get("to")) for edge in members]
                    targets = [item for item in targets if item]
                    expected_start = ({"x": source["x"] + source["width"], "y": source["y"] + source["height"] / 2}
                                      if source and diagram.get("direction") == "LR" else
                                      {"x": source["x"] + source["width"] / 2, "y": source["y"] + source["height"]}
                                      if source else None)
                    if not expected_start or not group.get("trunkPoints") or group["trunkPoints"][0] != expected_start:
                        branch_group_violations.append(f'{group["id"]}:fan_out_source_port')
                    if source and targets:
                        check_bus_channel(group, source.get("layer"), targets[0].get("layer"), "fan_out")
                    check_branches_reach_bus(group, "fan_out")
                    grouped_routes.append((group["id"], {group.get("sourceId"), *(edge.get("to") for edge in members)},
                                           group.get("trunkPoints", [])))
                    centers = sorted((item["y"] + item["height"] / 2 if diagram.get("direction") == "LR"
                                      else item["x"] + item["width"] / 2) for item in targets)
                    if any(second - first < 12 for first, second in zip(centers, centers[1:])):
                        branch_group_violations.append(f'{group["id"]}:branch_spacing')
                    if sum(bool(edge.get("showMarker")) for edge in members) != len(members):
                        branch_group_violations.append(f'{group["id"]}:target_arrow_count')
                elif group.get("pattern") == "fan_in":
                    target = source_nodes.get(group.get("targetId"))
                    expected_end = ({"x": target["x"], "y": target["y"] + target["height"] / 2}
                                    if target and diagram.get("direction") == "LR" else
                                    {"x": target["x"] + target["width"] / 2, "y": target["y"]}
                                    if target else None)
                    if not expected_end or group.get("targetArrowPoints", [None])[-1] != expected_end:
                        branch_group_violations.append(f'{group["id"]}:fan_in_target_port')
                    if any(edge.get("showMarker") for edge in members):
                        branch_group_violations.append(f'{group["id"]}:duplicate_target_arrows')
                    sources = [source_nodes.get(edge.get("from")) for edge in members]
                    sources = [item for item in sources if item]
                    if target and sources:
                        check_bus_channel(group, sources[0].get("layer"), target.get("layer"), "fan_in")
                    check_branches_reach_bus(group, "fan_in")
                    grouped_routes.append((group["id"], {group.get("targetId"), *(edge.get("from") for edge in members)},
                                           group.get("busPoints", [])))
                    grouped_routes.append((group["id"], {group.get("targetId"), *(edge.get("from") for edge in members)},
                                           group.get("targetArrowPoints", [])))
                    centers = sorted((source_nodes[edge["from"]]["y"] + source_nodes[edge["from"]]["height"] / 2
                                      if diagram.get("direction") == "LR" else
                                      source_nodes[edge["from"]]["x"] + source_nodes[edge["from"]]["width"] / 2)
                                     for edge in members if edge.get("from") in source_nodes)
                    if any(second - first < 12 for first, second in zip(centers, centers[1:])):
                        branch_group_violations.append(f'{group["id"]}:branch_spacing')
                elif group.get("pattern") == "bidirectional":
                    reverse_edges = [edge for edge in members if edge.get("returnEdge")]
                    if len(reverse_edges) != 1 or any(len(edge.get("points", [])) < 3 for edge in members):
                        branch_group_violations.append(f'{group["id"]}:return_track')
                    for edge in members:
                        grouped_routes.append((group["id"], {edge.get("from"), edge.get("to")}, edge.get("points", [])))

            raw_edges = {edge["id"]: edge for edge in diagram.get("edges", [])}
            for group in expected.get("groups", []):
                if group.get("pattern") not in {"fan_out", "fan_in"} or len(group["edgeIds"]) < 3:
                    continue
                for edge_id in group["edgeIds"]:
                    raw_edge = raw_edges[edge_id]
                    source_layout = source_nodes.get(raw_edge["from"])
                    expected_tag = f'→ {str(raw_edge.get("label", "")).strip()}'
                    tags = next((item.get("routeAnnotationLines", []) for item in layout.get("nodes", [])
                                 if item.get("id") == raw_edge["from"]), [])
                    if expected_tag.strip() != "→" and not any(expected_tag in str(tag) for tag in tags):
                        branch_group_violations.append(f'{group["id"]}:missing_source_usage:{raw_edge["from"]}')
                    if source_layout and any(text_width(str(tag), 10) > source_layout["width"] - 24 for tag in tags):
                        branch_group_violations.append(f'{group["id"]}:source_usage_overflow:{raw_edge["from"]}')
                    if source_layout and (source_layout.get("height") != FLOW_DETAIL_CARD_H or len(tags) > 2
                                          or len(source_layout.get("desc_lines", [])) > 1):
                        branch_group_violations.append(f'{group["id"]}:source_usage_slot_overlap:{raw_edge["from"]}')
                    if source_layout and tags:
                        text_boxes = []
                        if source_layout.get("title_lines"):
                            text_boxes.append((FLOW_DETAIL_TITLE_BASELINE - 15, FLOW_DETAIL_TITLE_BASELINE + 2))
                        text_boxes.extend((FLOW_DETAIL_DESC_BASELINE - 12, FLOW_DETAIL_DESC_BASELINE + 2)
                                          for _ in source_layout.get("desc_lines", []))
                        text_boxes.extend((FLOW_DETAIL_TAG_BASELINE + index * FLOW_DETAIL_TAG_LINE_HEIGHT - 10,
                                           FLOW_DETAIL_TAG_BASELINE + index * FLOW_DETAIL_TAG_LINE_HEIGHT + 2)
                                          for index, _ in enumerate(tags))
                        if any(first[1] > second[0] for first, second in zip(text_boxes, text_boxes[1:])) \
                                or (text_boxes and text_boxes[-1][1] > source_layout.get("height", 0)):
                            route_annotation_slot_violations.append(raw_edge["from"])
                    route = edge_map.get(edge_id, {})
                    if route.get("labelPosition") is not None:
                        branch_group_violations.append(f'{group["id"]}:branch_label_on_line')
        for group_id, endpoint_ids, points in grouped_routes:
            for first, second in zip(points, points[1:]):
                if first["x"] != second["x"] and first["y"] != second["y"]:
                    branch_group_violations.append(f"{group_id}:diagonal_segment")
                for node in nodes:
                    if node["id"] not in endpoint_ids and _axis_segment_hits_box(first, second, node):
                        branch_group_violations.append(f"{group_id}:route_through:{node['id']}")
        for edge in layout.get("edges", []):
            if not edge.get("labelPosition") or not str(edge.get("label", "")).strip():
                continue
            points = edge.get("points", [])
            if points and min(point_segment_distance(edge["labelPosition"], a, b)
                              for a, b in zip(points, points[1:])) > 12:
                label_distance_violations.append(edge["id"])
        for item in sorted(set(branch_group_violations)):
            issues.append({"code": "branch_group_invalid", "group": item,
                           "message": "分支边组未满足共享总线、端口、间距、标签或箭头数量约束"})
        for edge_id in sorted(set(label_distance_violations)):
            issues.append({"code": "label_too_far_from_edge", "edge": edge_id,
                           "message": "连线标签中心距所属连线超过 12px"})
        for node_id in sorted(set(route_annotation_slot_violations)):
            issues.append({"code": "route_annotation_text_overlap", "node": node_id,
                           "message": "来源卡片说明与固定分支用途标签位发生文字重叠"})
    overlaps = [(a["id"], b["id"]) for a, b in combinations(nodes, 2) if _overlap(a, b)]
    for a, b in overlaps:
        issues.append({"code": "node_overlap", "nodes": [a, b], "message": "模块边界发生重叠"})

    card_height_errors = []
    if diagram["type"] == "architecture":
        card_height_errors = [node["id"] for node in nodes if not 52 <= node["height"] <= 68]
        for node_id in card_height_errors:
            issues.append({"code": "architecture_card_height", "node": node_id,
                           "message": "架构图模块卡片高度应在 52px 至 68px 之间"})

    canvas_overflows = []
    for node in nodes:
        if node["x"] < 0 or node["y"] < 0 or node["x"] + node["width"] > layout["width"] or node["y"] + node["height"] > layout["height"]:
            canvas_overflows.append({"type": "node", "id": node["id"]})
    for layer in layout.get("layers", []):
        if layer["x"] < 0 or layer["y"] < 0 or layer["x"] + layer["width"] > layout["width"] or layer["y"] + layer["height"] > layout["height"]:
            canvas_overflows.append({"type": "layer", "id": layer["id"]})
    for item in canvas_overflows:
        issues.append({"code": "canvas_overflow", **item, "message": "模块或泳道超出 SVG 画布"})

    by_layer: dict[str, list[dict]] = {}
    cross_layers = {layer["id"] for layer in diagram["layers"] if layer.get("crossCutting")}
    for node in nodes:
        by_layer.setdefault(str(node.get("layer")), []).append(node)
    misaligned = []
    for layer_id, members in by_layer.items():
        # Architecture layers are horizontal swimlanes and must share a baseline.
        # In flow diagrams, a layer is a topological column/row; parallel branches
        # intentionally occupy separate tracks within that layer.
        if diagram["type"] != "architecture" or layer_id in cross_layers or len(members) < 2:
            continue
        rows: dict[int, list[dict]] = {}
        for node in members:
            rows.setdefault(int(node.get("row", 0)), []).append(node)
        if any(len({round(node["y"], 1) for node in row}) > 1 for row in rows.values()):
            misaligned.append(layer_id)
            issues.append({"code": "baseline_misalignment", "layer": layer_id, "message": "同层同排模块没有对齐"})

    diagonal = []
    excessive_bends = []
    main_bends = []
    edge_segments: list[tuple[dict, dict, dict]] = []
    bidirectional_edge_ids = {edge_id for group in layout.get("edgeGroups", [])
                              if group.get("pattern") == "bidirectional"
                              for edge_id in group.get("edgeIds", [])}
    for edge in layout.get("edges", []):
        points = edge.get("points", [])
        for first, second in zip(points, points[1:]):
            if first["x"] != second["x"] and first["y"] != second["y"]:
                diagonal.append(edge["id"])
            edge_segments.append((edge, first, second))
        bends = max(0, len(points) - 2)
        if edge.get("main") and bends > 0 and edge.get("id") not in bidirectional_edge_ids:
            main_bends.append(edge["id"])
        if edge.get("id") in bidirectional_edge_ids and bends > 4:
            excessive_bends.append(edge["id"])
        elif edge.get("id") not in bidirectional_edge_ids and bends > 2:
            excessive_bends.append(edge["id"])
    directional_port_errors = []
    port_outset_errors = []
    if diagram["type"] == "architecture" or hardcoded_ports:
        grouped_edge_ids = {edge_id for group in layout.get("edgeGroups", [])
                            for edge_id in group.get("edgeIds", [])
                            if group.get("pattern") in {"fan_out", "fan_in", "bidirectional"}}
        for edge in layout.get("edges", []):
            if edge.get("layerFlow") or edge["from"] not in node_map or edge["to"] not in node_map:
                continue
            # Fan branches intentionally begin/end on a shared bus. Their true
            # module ports are audited once at the group level above.
            if edge.get("id") in grouped_edge_ids:
                continue
            source, target = node_map[edge["from"]], node_map[edge["to"]]
            points = edge.get("points", [])
            sx, sy = source["x"] + source["width"] / 2, source["y"] + source["height"] / 2
            tx, ty = target["x"] + target["width"] / 2, target["y"] + target["height"] / 2
            # Match the router's declared topology for flow details. A node
            # pair's geometric offset must not change which edge ports are
            # considered valid.
            horizontal = (source.get("layer") == target.get("layer")
                          if diagram["type"] == "architecture" else
                          diagram.get("direction") == "LR")
            if horizontal:
                forward = tx >= sx
                expected_start = {"x": source["x"] + source["width"] if forward else source["x"], "y": sy}
                expected_end = {"x": target["x"] if forward else target["x"] + target["width"], "y": ty}
            else:
                downward = ty >= sy
                expected_start = {"x": sx, "y": source["y"] + source["height"] if downward else source["y"]}
                expected_end = {"x": tx, "y": target["y"] if downward else target["y"] + target["height"]}
            if len(points) < 2 or points[0] != expected_start or points[-1] != expected_end:
                directional_port_errors.append(edge["id"])
                continue
            expected_axis = "x" if horizontal else "y"
            for point_a, point_b in ((points[0], points[1]), (points[-2], points[-1])):
                length = abs(point_a[expected_axis] - point_b[expected_axis])
                parallel_delta = abs(point_a["x" if expected_axis == "y" else "y"] - point_b["x" if expected_axis == "y" else "y"])
                if parallel_delta or (len(points) > 2 and length < 16):
                    port_outset_errors.append(edge["id"])
                    break
        for edge_id in directional_port_errors:
            issues.append({"code": "directional_port", "edge": edge_id,
                           "message": "连线没有使用与关系方向匹配的模块边缘中点端口"})
        for edge_id in sorted(set(port_outset_errors)):
            issues.append({"code": "port_outset", "edge": edge_id,
                           "message": "端口外引段不足 16px 或未沿边缘法线延伸"})
    if diagonal:
        issues.extend({"code": "diagonal_edge", "edge": edge_id, "message": "连线含斜线段"} for edge_id in sorted(set(diagonal)))
    if main_bends:
        issues.append({"code": "main_edge_bend", "edges": main_bends, "message": "主链路连线存在折点"})
    if excessive_bends:
        issues.append({"code": "too_many_bends", "edges": excessive_bends, "message": "连线折点超过 2 个"})

    crossings: set[tuple[str, str]] = set()
    for (edge_a, a, b), (edge_b, c, d) in combinations(edge_segments, 2):
        if edge_a["id"] == edge_b["id"] or {edge_a["from"], edge_a["to"]} & {edge_b["from"], edge_b["to"]}:
            continue
        if _segment_intersection(a, b, c, d):
            crossings.add(tuple(sorted((edge_a["id"], edge_b["id"]))))
    for edge_a, edge_b in sorted(crossings):
        issues.append({"code": "edge_crossing", "edges": [edge_a, edge_b], "message": "两条连线发生交叉"})

    blocked_edges = []
    for edge, first, second in edge_segments:
        for node in nodes:
            if node["id"] in {edge["from"], edge["to"]}:
                continue
            x1, x2 = sorted((first["x"], second["x"]))
            y1, y2 = sorted((first["y"], second["y"]))
            if first["y"] == second["y"]:
                hit = y1 > node["y"] and y1 < node["y"] + node["height"] and x2 > node["x"] and x1 < node["x"] + node["width"]
            elif first["x"] == second["x"]:
                hit = x1 > node["x"] and x1 < node["x"] + node["width"] and y2 > node["y"] and y1 < node["y"] + node["height"]
            else:
                hit = False
            if hit:
                blocked_edges.append(edge["id"])
                break
    for edge_id in sorted(set(blocked_edges)):
        issues.append({"code": "edge_through_node", "edge": edge_id, "message": "连线穿过无关模块"})

    text_overflow = []
    for node_id, position in node_map.items():
        max_width = position["width"] - 32
        source = diagram_nodes[node_id]
        title_lines = position.get("title_lines", [source["title"]])
        desc_lines = position.get("desc_lines", [])
        compact_text = diagram["type"] == "architecture" or hardcoded_ports
        title_font = 14 if contract_v2 else (15 if compact_text else 20)
        desc_font = 12 if compact_text else 13
        if any(text_width(line, title_font) > max_width for line in title_lines) or any(text_width(line, desc_font) > max_width for line in desc_lines):
            text_overflow.append(node_id)
    for node_id in text_overflow:
        issues.append({"code": "text_overflow", "node": node_id, "message": "模块文字宽度超过卡片"})

    labels = []
    label_overlaps = []
    for edge in layout.get("edges", []):
        if diagram.get("showEdgeLabels") is False and not (contract_v2 and edge.get("layerFlow")):
            continue
        if edge.get("showLabel") is False:
            continue
        if edge.get("kind") == "governance":
            continue
        if not str(edge.get("label", "")).strip():
            continue
        points = edge.get("points", [])
        if len(points) < 2:
            continue
        if edge.get("labelPosition"):
            center = edge["labelPosition"]
        else:
            a, b = max(zip(points, points[1:]), key=lambda pair: abs(pair[0]["x"] - pair[1]["x"]) + abs(pair[0]["y"] - pair[1]["y"]))
            center = {"x": (a["x"] + b["x"]) / 2, "y": (a["y"] + b["y"]) / 2 - (10 if a["y"] == b["y"] else 2)}
        compact_label = diagram["type"] == "architecture" or hardcoded_ports
        label_char_width = 11 if compact_label else 15
        label_width = max(52, len(edge["label"]) * label_char_width + (10 if compact_label else 18))
        box = {"id": edge["id"], "x": center["x"] - label_width / 2, "y": center["y"] - 13,
               "width": label_width, "height": 22}
        for node in nodes:
            if _overlap(box, node):
                label_overlaps.append(edge["id"])
        if contract_v2:
            for lane in layout.get("layers", []):
                header_boxes = [
                    {"x": lane["x"] + 10, "y": lane["y"] + 7,
                     "width": text_width(lane.get("name", ""), 16) + 20, "height": 24},
                    {"x": lane["x"] + 10, "y": lane["y"] + 30,
                     "width": text_width(lane.get("desc", ""), 12) + 20, "height": 20},
                ]
                if any(rect["width"] > 20 and _overlap(box, rect) for rect in header_boxes):
                    label_overlaps.append(edge["id"])
        for other in labels:
            if _overlap(box, other):
                label_overlaps.extend((edge["id"], other["id"]))
        labels.append(box)
    for edge_id in sorted(set(label_overlaps)):
        issues.append({"code": "label_overlap", "edge": edge_id, "message": "连线标签和节点或其他标签重叠"})

    if contract_v2:
        lane_map = {layer["id"]: layer for layer in layout.get("layers", [])}
        ordinary_lane_order = [layer["id"] for layer in layout.get("layers", [])
                               if not layer.get("crossCutting")]
        row_groups: dict[tuple[str, int], list[dict]] = {}
        row_symmetry = []
        for node in nodes:
            row_groups.setdefault((str(node.get("layer")), int(node.get("row", 0))), []).append(node)
        for (layer_id, row_number), row_items in row_groups.items():
            lane = lane_map.get(layer_id)
            if lane is None or lane.get("crossCutting"):
                continue
            left = min(item["x"] for item in row_items) - lane["x"]
            right = lane["x"] + lane["width"] - max(item["x"] + item["width"] for item in row_items)
            difference = round(abs(left - right), 2)
            row_symmetry.append({"layer": layer_id, "row": row_number,
                                 "leftWhitespacePx": round(left, 2),
                                 "rightWhitespacePx": round(right, 2),
                                 "differencePx": difference})
            if difference > 1:
                issues.append({"code": "row_not_centered", "layer": layer_id, "row": row_number,
                               "differencePx": difference,
                               "message": "同层每一排必须独立居中，左右留白差不得超过 1px"})
        if len({item.get("width") for item in nodes}) > 1:
            issues.append({"code": "global_card_width_mismatch",
                           "message": "全图模块卡片必须使用同一宽度"})
        for node_id, position in node_map.items():
            source = diagram_nodes[node_id]
            title = "".join(str(source.get("title", "")).split())
            desc = "".join(str(source.get("desc", "")).split())
            if len(title) > 10 or len(position.get("title_lines", [])) != 1:
                issues.append({"code": "v2_title_wrap_or_overflow", "node": node_id,
                               "message": "新版主图标题最多 10 字且必须单行显示"})
            if len(desc) > 12 or "…" in desc or "..." in desc:
                issues.append({"code": "v2_description_too_long", "node": node_id,
                               "message": "新版主图说明最多 12 字，禁止省略号截断"})
        non_channel_edges = sorted({edge.get("id", "<无 ID>") for edge in diagram.get("edges", [])}
                                   | {edge.get("id", "<无 ID>") for edge in layout.get("edges", [])
                                      if not edge.get("layerFlow")})
        if non_channel_edges:
            issues.append({"code": "module_edges_on_architecture_main", "edges": non_channel_edges,
                           "message": "架构主图只允许泳道间主流向；模块间关系放入下钻图"})

        channel_violations = []
        pair_counts: dict[tuple[str, str], list[str]] = {}
        for edge in layout.get("edges", []):
            if not edge.get("layerFlow"):
                continue
            pair = tuple(sorted((str(edge.get("from")), str(edge.get("to")))))
            pair_counts.setdefault(pair, []).append(str(edge.get("id", "<无 ID>")))
            source = lane_map.get(edge.get("from"))
            target = lane_map.get(edge.get("to"))
            points = edge.get("points", [])
            if not source or not target or len(points) != 2:
                issues.append({"code": "invalid_layer_channel", "edge": edge["id"],
                               "message": "层间通道必须是相邻泳道边界间的一段直线"})
                continue
            if (source["id"] not in ordinary_lane_order or target["id"] not in ordinary_lane_order
                    or abs(ordinary_lane_order.index(source["id"]) - ordinary_lane_order.index(target["id"])) != 1):
                channel_violations.append(edge["id"])
            expected_x = source["x"] + source["width"] / 2
            reverse = target["y"] < source["y"]
            expected_start = {"x": expected_x,
                              "y": source["y"] if reverse else source["y"] + source["height"]}
            expected_end = {"x": expected_x,
                            "y": target["y"] + target["height"] if reverse else target["y"]}
            if points[0] != expected_start or points[1] != expected_end:
                issues.append({"code": "layer_channel_not_centered", "edge": edge["id"],
                               "message": "层间箭头必须位于相邻泳道的水平中点并连接边界"})
            for first, second in zip(points, points[1:]):
                if any(_axis_segment_hits_box(first, second,
                                              {key: lane[key] for key in ("x", "y", "width", "height")})
                       for lane in layout.get("layers", [])):
                    channel_violations.append(edge["id"])
                    break
        for pair, edge_ids in pair_counts.items():
            if len(edge_ids) > 1:
                issues.append({"code": "duplicate_layer_pair_flow", "layers": list(pair),
                               "edges": sorted(edge_ids),
                               "message": "相邻泳道之间最多保留一条层间通道"})
        for edge_id in sorted(set(channel_violations)):
            issues.append({"code": "edge_outside_reserved_channel", "edge": edge_id,
                           "message": "连线必须完整留在相邻泳道之间的预留通道内"})

        contrast_failures = _contrast_failures(layout)
        if contrast_failures:
            issues.append({"code": "contrast_below_wcag_aa", "elements": sorted(set(contrast_failures)),
                           "message": "文字与背景对比度低于 4.5:1"})

        ratio = (layout.get("width", 0) / layout.get("height", 1)) if layout.get("height") else 0
        if not 1.2 <= ratio <= 1.8:
            issues.append({"code": "canvas_aspect_ratio", "ratio": round(ratio, 3),
                           "message": "主图宽高比应在 1.2 至 1.8；请调整展示分组或拆图，不得缩放字号"})
        if layout.get("width") != 1440:
            issues.append({"code": "canvas_width_not_fixed", "width": layout.get("width"),
                           "message": "新版架构图画布宽度必须固定为 1440px"})
        lane_utilizations = []
        for lane in layout.get("layers", []):
            if lane.get("crossCutting"):
                continue
            lane_nodes = [item for item in nodes if item.get("layer") == lane.get("id")]
            if lane_nodes:
                usable_height = max(1, lane["height"] - 58 - 8 - 8)
                if any(frame.get("layer") == lane.get("id") for frame in layout.get("groupFrames", [])):
                    usable_height = max(1, usable_height - 22)
                occupied_height = max(item["y"] + item["height"] for item in lane_nodes) - min(item["y"] for item in lane_nodes)
                lane_utilizations.append(occupied_height / usable_height)
        if lane_utilizations and min(lane_utilizations) < 0.70:
            issues.append({"code": "layer_height_utilization", "utilization": round(min(lane_utilizations), 3),
                           "message": "至少一条泳道内容高度利用率低于 70%；请收紧留白或调整分组"})

        header_intersections = []
        for lane in layout.get("layers", []):
            title_rect = {"x": lane["x"] + 10, "y": lane["y"] + 7,
                          "width": text_width(lane.get("name", ""), 16) + 20, "height": 24}
            desc_rect = {"x": lane["x"] + 10, "y": lane["y"] + 30,
                         "width": text_width(lane.get("desc", ""), 12) + 20, "height": 20}
            for edge in layout.get("edges", []):
                if any(_axis_segment_hits_box(a, b, rect)
                       for a, b in zip(edge.get("points", []), edge.get("points", [])[1:])
                       for rect in (title_rect, desc_rect) if rect["width"] > 20):
                    header_intersections.append((edge["id"], lane["id"]))
        for edge_id, layer_id in sorted(set(header_intersections)):
            issues.append({"code": "edge_through_layer_text", "edge": edge_id, "layer": layer_id,
                           "message": "连线与泳道标题或副标题相交"})

    return {
        "passed": not issues,
        "counts": {"node_overlaps": len(overlaps), "edge_crossings": len(crossings), "text_overflows": len(text_overflow),
                   "canvas_overflows": len(canvas_overflows),
                   "diagonal_edges": len(set(diagonal)), "main_edges_with_bends": len(main_bends),
                   "edges_over_two_bends": len(set(excessive_bends)), "label_overlaps": len(set(label_overlaps)),
                   "architecture_card_height_errors": len(card_height_errors),
                   "directional_port_errors": len(directional_port_errors),
                   "port_outset_errors": len(set(port_outset_errors)),
                   "branch_group_violations": len(set(branch_group_violations)),
                   "label_distance_violations": len(set(label_distance_violations)),
                   "route_annotation_slot_violations": len(set(route_annotation_slot_violations)),
                   "visible_arrow_count": visible_arrow_count + sum(
                       group.get("pattern") == "fan_in" for group in layout.get("edgeGroups", [])),
                   "arrow_marker_violations": sum(issue["code"] == "arrow_marker_invalid" for issue in issues),
                   "chain_badge_violations": sum(issue["code"] == "chain_badge_overlap" for issue in issues),
                   "duplicate_layer_flow_label_violations": sum(issue["code"] == "duplicate_layer_flow_labels" for issue in issues),
                   "crosscut_label_violations": sum(issue["code"] == "crosscut_label_duplicate" for issue in issues),
                   "legend_footer_gap_violations": sum(issue["code"] == "legend_footer_gap" for issue in issues),
                   "layer_channel_violations": sum(issue["code"] in {
                       "module_edges_on_architecture_main", "invalid_layer_channel",
                       "layer_channel_not_centered", "edge_outside_reserved_channel"} for issue in issues)},
        "canvas": {"width": layout.get("width"), "height": layout.get("height"),
                   "aspectRatio": round(layout.get("width", 0) / max(1, layout.get("height", 1)), 3)},
        "rowSymmetry": {
            "maxDifferencePx": max((item["differencePx"] for item in row_symmetry), default=0),
            "rows": row_symmetry,
        } if contract_v2 else None,
        "issues": issues,
    }


def _axis_segment_hits_box(a: dict, b: dict, box: dict) -> bool:
    if a["y"] == b["y"]:
        return (box["y"] < a["y"] < box["y"] + box["height"]
                and max(min(a["x"], b["x"]), box["x"]) < min(max(a["x"], b["x"]), box["x"] + box["width"]))
    if a["x"] == b["x"]:
        return (box["x"] < a["x"] < box["x"] + box["width"]
                and max(min(a["y"], b["y"]), box["y"]) < min(max(a["y"], b["y"]), box["y"] + box["height"]))
    return False


def _contrast_ratio(foreground: str, background: str) -> float:
    def luminance(color: str) -> float:
        raw = color.lstrip("#")
        channels = [int(raw[index:index + 2], 16) / 255 for index in (0, 2, 4)]
        linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
                  for value in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    high, low = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _contrast_failures(layout: dict) -> list[str]:
    failures = []
    fixed_pairs = [("卡片标题", "#163354", "#FFFFFF"),
                   ("卡片说明", "#52657E", "#FFFFFF"),
                   ("图例", "#475569", "#F8FAFC")]
    for name, foreground, background in fixed_pairs:
        if _contrast_ratio(foreground, background) < 4.5:
            failures.append(name)
    for index, lane in enumerate(layout.get("layers", [])):
        style = _layer_style(lane, index, architecture=True)
        if _contrast_ratio("#183153", style["fill"]) < 4.5:
            failures.append(f"{lane.get('name', lane.get('id'))}层标题")
        if _contrast_ratio("#52657E", style["fill"]) < 4.5:
            failures.append(f"{lane.get('name', lane.get('id'))}层说明")
        if lane.get("crossCutting") and _contrast_ratio("#C2410C", "#FFF7ED") < 4.5:
            failures.append("贯穿标记")
    return sorted(set(failures))
