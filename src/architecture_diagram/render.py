"""中文浅色 SVG 与离线可编辑 HTML 渲染器。"""

from __future__ import annotations

import html
import hashlib
import json
import re
from typing import Any

from .layout import (FLOW_DETAIL_DESC_BASELINE, FLOW_DETAIL_TAG_BASELINE,
                     FLOW_DETAIL_TAG_LINE_HEIGHT, FLOW_DETAIL_TITLE_BASELINE,
                     layout_diagram, text_width, wrap_text)
from .versioning import LAYOUT_ALGORITHM_VERSION, RENDERER_VERSION


PALETTE = ["#EFF6FF", "#F0FDF4", "#F5F3FF", "#FFFBEB", "#ECFEFF", "#FFF7ED"]
LEGACY_PALETTE = ["#DBEAFE", "#DCFCE7", "#F3E8FF", "#FEF3C7", "#E0F2FE", "#FFE4E6"]
LAYER_STYLES = {
    "access": {"fill": "#EFF6FF", "stroke": "#3B82F6"},
    "orchestration": {"fill": "#F0FDF4", "stroke": "#22C55E"},
    "capability": {"fill": "#F5F3FF", "stroke": "#8B5CF6"},
    "business": {"fill": "#FFFBEB", "stroke": "#F59E0B"},
    "data": {"fill": "#ECFEFF", "stroke": "#06B6D4"},
    "governance": {"fill": "#FFF7ED", "stroke": "#F97316"},
    "other": {"fill": "#F1F5F9", "stroke": "#64748B"},
}
PAD = 36
IMPLEMENTATION_STATUS = {"implemented": "已实现", "partial": "部分实现", "config_only": "仅配置", "unknown": "待确认"}
ARROW_STANDARD_LENGTH = 12
ARROW_STANDARD_HEIGHT = 10
ARROW_MAIN_LENGTH = 18
ARROW_MAIN_HEIGHT = 14
EDGE_COLORS = {"main": "#155EEF", "secondary": "#94A3B8", "async": "#7C3AED", "data": "#0F766E"}
_SVG_STYLE = "text{font-family:'Microsoft YaHei','Noto Sans CJK SC',sans-serif}.diagram-title,.layer-title,.node-title{font-size:20px;font-weight:700;fill:#0f172a}.layer-desc,.node-desc,.drill,.edge-label text{font-size:13px;fill:#52657e}.node-title{fill:#163354}.layer-title{fill:#183153}.architecture-diagram .layer-title{font-size:16px}.architecture-diagram .layer-desc{font-size:12px}.architecture-diagram .compact .node-title{font-size:14px}.architecture-diagram .compact .node-desc{font-size:12px}.architecture-diagram .compact .drill{font-size:10px}.architecture-diagram .edge-label text,.architecture-detail .edge-label text{font-size:11px}.edge-line,.edge-group-line,.edge-group-arrow{stroke-linejoin:round;stroke-linecap:butt}.route-annotation{font-size:10px;fill:#64748B}.lifeline{stroke:#94a3b8;stroke-width:1.4;stroke-dasharray:5 6}.main-chain{font-size:13px;font-weight:600;fill:#334155}.chain-badge circle{fill:#EFF6FF;stroke:#3B82F6;stroke-width:1.2}.chain-badge text{font-size:11px;font-weight:700;fill:#1D4ED8}.group-frame text{font-size:11px;font-weight:600;fill:#64748B}.crosscut-mark text{font-size:10px;font-weight:600;fill:#C2410C}.diagram-legend .legend-text{font-size:12px;fill:#475569}.matrix-axis{font-size:12px;fill:#64748B}.matrix-cell text{font-size:12px;fill:#334155}"
_SVG_STYLE += ".architecture-detail .compact .node-title{font-size:15px}.architecture-detail .compact .node-desc{font-size:12px}.architecture-detail .compact .drill{font-size:10px}.architecture-diagram .compact:has(.drill-icon) .node-title,.architecture-detail .compact:has(.drill-icon) .node-title{transform:translateX(-16px)}"


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _path(points: list[dict]) -> str:
    if not points:
        return ""
    return "M " + " L ".join(f"{point['x']:.1f} {point['y']:.1f}" for point in points)


def _edge_color(edge: dict, *, architecture: bool = False) -> str:
    explicit = edge.get("strokeColor")
    if isinstance(explicit, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", explicit):
        return explicit.upper()
    if edge.get("kind") == "governance":
        return (LAYER_STYLES["governance"]["stroke"] if architecture else "#D4A24C")
    if edge.get("groupPattern") in {"fan_out", "fan_in"}:
        return "#64748B"
    if architecture:
        if edge.get("layerFlow"):
            return EDGE_COLORS["main"]
        if edge.get("main"):
            return "#475569"
        if edge.get("kind") in {"db_read", "db_write", "cache", "vector_query"}:
            return "#0891B2"
        return "#64748B"
    if edge.get("returnEdge"):
        return "#7C3AED"
    if edge.get("async"):
        return EDGE_COLORS["async"]
    if edge.get("main"):
        return EDGE_COLORS["main"]
    if edge.get("kind") in {"db_read", "db_write", "cache", "vector_query"}:
        return EDGE_COLORS["data"]
    return EDGE_COLORS["secondary"]


def _marker_id(color: str, *, main: bool = False) -> str:
    """Key markers by line color and visual class so the head always matches its shaft."""
    prefix = "arrow-main-" if main else "arrow-"
    return prefix + re.sub(r"[^0-9A-Fa-f]", "", color).upper()


def _marker_definition(color: str, *, main: bool = False) -> str:
    head_length = ARROW_MAIN_LENGTH if main else ARROW_STANDARD_LENGTH
    head_height = ARROW_MAIN_HEIGHT if main else ARROW_STANDARD_HEIGHT
    marker_id = _marker_id(color, main=main)
    return (f'<marker id="{marker_id}" viewBox="0 0 {head_length} {head_height}" '
            f'markerWidth="{head_length}" markerHeight="{head_height}" '
            f'refX="0" refY="{head_height / 2:g}" '
            f'orient="auto" markerUnits="userSpaceOnUse">'
            f'<path d="M 0 0 L {head_length} {head_height / 2:g} L 0 {head_height} Z" fill="{color}"/></marker>')


def _arrow_shaft_points(points: list[dict], *, main: bool = False) -> list[dict]:
    """Stop the shaft at the arrowhead base; the marker projects forward to the original tip."""
    if len(points) < 2:
        raise ValueError("带箭头的连线至少需要两个路径点")
    length = ARROW_MAIN_LENGTH if main else ARROW_STANDARD_LENGTH
    result = [dict(point) for point in points]
    tip, previous = result[-1], result[-2]
    dx, dy = tip["x"] - previous["x"], tip["y"] - previous["y"]
    segment_length = (dx * dx + dy * dy) ** 0.5
    if segment_length + 1e-6 < length:
        raise ValueError(f"箭头末段仅 {segment_length:.1f}px，短于箭头长度 {length}px")
    result[-1] = {"x": tip["x"] - dx / segment_length * length,
                  "y": tip["y"] - dy / segment_length * length}
    return result


def _layer_style(layer: dict, index: int, *, architecture: bool) -> dict[str, str]:
    if architecture:
        if layer.get("crossCutting"):
            return LAYER_STYLES["governance"]
        pipeline_type = {"offline": "data", "online": "access"}.get(layer.get("pipeline"))
        if pipeline_type:
            return LAYER_STYLES[pipeline_type]
        template_role_type = {"publicApi": "access", "kernel": "capability",
                              "extensions": "capability", "tooling": "other"}.get(layer.get("templateRole"))
        if template_role_type:
            return LAYER_STYLES[template_role_type]
        standard_type = layer.get("standardType")
        if standard_type in LAYER_STYLES:
            return LAYER_STYLES[standard_type]
        name = layer.get("name", "")
        if any(token in name for token in ("接入", "入口")):
            key = "access"
        elif any(token in name for token in ("编排", "路由", "调度")):
            key = "orchestration"
        elif any(token in name for token in ("能力", "工具")):
            key = "capability"
        elif any(token in name for token in ("业务服务", "业务层")):
            key = "business"
        elif any(token in name for token in ("数据", "存储", "依赖")):
            key = "data"
        else:
            key = ("access", "orchestration", "capability", "business", "data")[index % 5]
        return LAYER_STYLES[key]
    if layer.get("crossCutting"):
        return {"fill": "#FFF9ED", "stroke": "#D6A85F"}
    return {"fill": LEGACY_PALETTE[index % len(LEGACY_PALETTE)], "stroke": "#C7D6EA"}


def _render_layer(layer: dict, index: int, *, architecture: bool = False) -> str:
    style = _layer_style(layer, index, architecture=architecture)
    title_color = ' fill="#183153"' if architecture else ""
    title = str(layer["name"])
    desc = str(layer.get("desc", ""))
    if layer.get("crossCutting"):
        title = title.replace("贯穿所有层", "").strip(" ：:（）()—-")
        desc = desc.replace("贯穿所有层", "").strip(" ：:（）()—-")
    label = f'<text class="layer-title"{title_color} x="{layer["x"] + 18}" y="{layer["y"] + 27}">{_esc(title)}</text>'
    if desc:
        label += f'<text class="layer-desc" x="{layer["x"] + 18}" y="{layer["y"] + 47}">{_esc(desc)}</text>'
    if layer.get("crossCuttingLabel"):
        label += (f'<g class="crosscut-mark"><rect x="{layer["x"] + layer["width"] - 102}" y="{layer["y"] + 7}" '
                  f'width="84" height="19" rx="9" fill="#FFF7ED" stroke="#FDBA74"/>'
                  f'<text x="{layer["x"] + layer["width"] - 60}" y="{layer["y"] + 20}" text-anchor="middle">'
                  f'{_esc(layer["crossCuttingLabel"])}</text></g>')
    return (f'<g class="layer" data-layer="{_esc(layer["id"])}"><rect x="{layer["x"]}" y="{layer["y"]}" '
            f'width="{layer["width"]}" height="{layer["height"]}" rx="16" fill="{style["fill"]}" stroke="{style["stroke"]}" stroke-width="1.4"/>{label}</g>')


def _render_v2_legend(diagram: dict, layout: dict) -> str:
    if layout.get("contractVersion") != 2:
        return ""
    type_names = {"access": "接入", "orchestration": "编排", "capability": "能力",
                  "business": "业务", "data": "数据", "governance": "治理", "other": "扩展"}
    chips = []
    seen_styles = set()
    lanes = layout.get("layers", [])
    lane_index = {lane["id"]: index for index, lane in enumerate(lanes)}
    for lane in lanes:
        style = _layer_style(lane, lane_index[lane["id"]], architecture=True)
        pipeline_name = {"offline": "离线", "online": "在线"}.get(lane.get("pipeline"))
        role_name = {"publicApi": "公共接口", "kernel": "核心内核",
                     "extensions": "适配扩展", "tooling": "工具链",
                     "deployment": "部署分区"}.get(lane.get("templateRole"))
        name = pipeline_name or role_name or type_names.get(lane.get("standardType")) or lane.get("name", "扩展")[:2]
        style_key = (style["fill"], style["stroke"], name)
        if style_key in seen_styles:
            continue
        seen_styles.add(style_key)
        chips.append((style["fill"], style["stroke"], name))
    # Keep the legend in the reserved bottom margin so it cannot collide with
    # a long title or the main-chain summary.
    x = PAD
    y = layout.get("height", 800) - 31
    parts = ['<g class="diagram-legend" aria-label="图例">']
    for fill, stroke, name in chips:
        parts.append(f'<rect x="{x}" y="{y}" width="10" height="10" rx="2" fill="{fill}" stroke="{stroke}" stroke-width="1.2"/>')
        parts.append(f'<text x="{x + 14}" y="{y + 10}" class="legend-text">{_esc(name)}</text>')
        x += 14 + text_width(name, 12) + 10
    parts.append(f'<path data-legend-key="main" data-marker-size="main" data-arrow-shaft-x="{x + 16}" data-arrow-shaft-y="{y + 5}" data-arrow-tip-x="{x + 34}" data-arrow-tip-y="{y + 5}" d="M {x + 2} {y + 5} L {x + 16} {y + 5}" stroke="#155EEF" stroke-width="3.6" stroke-linecap="butt" marker-end="url(#{_marker_id("#155EEF", main=True)})"/>')
    parts.append(f'<text x="{x + 40}" y="{y + 10}" class="legend-text">层间连接</text>')
    # The root swimlane legend already explains its ordinary solid flow arrow.
    # Add only extra styles actually present, such as governance constraints
    # and group frames.
    extra = [item for item in _detail_legend_specs(diagram, layout) if item["key"] != "main"]
    parts.append(_render_legend_items(extra, layout, start_x=x + 140, y=y + 5))
    parts.append("</g>")
    return "".join(parts)


def _detail_legend_specs(diagram: dict, layout: dict) -> list[dict[str, str | bool]]:
    """Return the visual line/frame styles that a graph actually uses."""
    architecture = diagram.get("type") == "architecture"
    specs: list[dict[str, str | bool]] = []
    seen: set[str] = set()
    grouped_edge_ids = {
        edge_id for group in layout.get("edgeGroups", [])
        if group.get("pattern") in {"fan_out", "fan_in"}
        for edge_id in group.get("edgeIds", [])
    }

    def add(key: str, label: str, color: str, dash: str = "", marker: bool = True,
            shape: str = "line") -> None:
        if key not in seen:
            specs.append({"key": key, "label": label, "color": color,
                          "dash": dash, "marker": marker, "shape": shape})
            seen.add(key)

    for edge in layout.get("edges", []):
        if edge.get("id") in grouped_edge_ids:
            continue
        if edge.get("kind") == "governance":
            add("governance", "治理约束", _edge_color(edge, architecture=architecture), "5 5", True)
        elif edge.get("returnEdge"):
            add("return", "返回关系", _edge_color(edge, architecture=architecture), "5 4")
        elif edge.get("async"):
            add("async", "异步调用", _edge_color(edge, architecture=architecture), "7 6")
        elif edge.get("main"):
            add("main", "主链路", _edge_color(edge, architecture=architecture))
        elif edge.get("kind") in {"db_read", "db_write", "cache", "vector_query"}:
            add("data", "数据访问", _edge_color(edge, architecture=architecture))
        else:
            add("secondary", "一般调用", _edge_color(edge, architecture=architecture))
    grouped_kinds = {group.get("kind") for group in layout.get("edgeGroups", [])
                     if group.get("pattern") in {"fan_out", "fan_in"}}
    if "governance" in grouped_kinds:
        add("governance", "治理约束", _edge_color({"kind": "governance"}, architecture=architecture), "5 5", True)
    if grouped_edge_ids and any(kind != "governance" for kind in grouped_kinds):
        add("branch", "分支调用", "#64748B")
    if diagram.get("type") == "sequence" or layout.get("lifelines"):
        add("lifeline", "参与者生命线", "#94A3B8", "5 6", False)
    if layout.get("groupFrames"):
        add("group", "职责分组", "#94A3B8", "4 4", False, "frame")
    return specs


def _render_legend_items(items: list[dict[str, str | bool]], layout: dict, *,
                         start_x: float = PAD, y: float | None = None) -> str:
    if not items:
        return ""
    height = layout.get("height", 800)
    baseline = float(y if y is not None else height - 18)
    x = float(start_x)
    parts = []
    for item in items:
        color = str(item["color"])
        dash = f' stroke-dasharray="{item["dash"]}"' if item["dash"] else ""
        if item["shape"] == "frame":
            parts.append(f'<rect data-legend-key="{item["key"]}" x="{x:.1f}" y="{baseline - 7:.1f}" width="22" height="12" rx="2" '
                         f'fill="none" stroke="{color}" stroke-width="1.4"{dash}/>')
        else:
            marker_main = bool(item.get("mainMarker"))
            marker = (f' marker-end="url(#{_marker_id(color, main=marker_main)})"' if item["marker"] else "")
            head_length = ARROW_MAIN_LENGTH if marker_main else ARROW_STANDARD_LENGTH
            shaft_end = x + 24 - head_length if item["marker"] else x + 24
            arrow_geometry = (f' data-arrow-shaft-x="{shaft_end:.1f}" data-arrow-shaft-y="{baseline - 2:.1f}" '
                              f'data-arrow-tip-x="{x + 24:.1f}" data-arrow-tip-y="{baseline - 2:.1f}"'
                              if item["marker"] else "")
            parts.append(f'<path data-legend-key="{item["key"]}"{arrow_geometry} d="M {x:.1f} {baseline - 2:.1f} L {shaft_end:.1f} {baseline - 2:.1f}" '
                          f'fill="none" stroke="{color}" stroke-width="{3.6 if marker_main else 1.8}" stroke-linecap="butt"{dash}{marker}/>')
        label = str(item["label"])
        parts.append(f'<text x="{x + 30:.1f}" y="{baseline + 2:.1f}" class="legend-text">{_esc(label)}</text>')
        x += 30 + text_width(label, 12) + 15
    return "".join(parts)


def _render_detail_legend(diagram: dict, layout: dict) -> str:
    items = _detail_legend_specs(diagram, layout)
    if not items:
        return ""
    top = layout.get("height", 800) - 25
    return ('<g class="diagram-legend" aria-label="连线图例">' +
            _render_legend_items(items, layout, y=top + 5) + '</g>')


def _render_edge(edge: dict, *, architecture: bool = False, compact_label: bool = False,
                 show_label: bool = True) -> str:
    color = _edge_color(edge, architecture=architecture)
    main_arrow = architecture and bool(edge.get("layerFlow"))
    width = float(edge.get("strokeWidth", 3.6 if main_arrow else 1.8))
    governance = edge.get("kind") == "governance"
    dash = (' stroke-dasharray="5 5"' if governance else
            ' stroke-dasharray="5 4"' if edge.get("returnEdge") else
            ' stroke-dasharray="7 6"' if edge.get("async") else "")
    points = edge.get("points", [])
    has_marker = edge.get("showMarker") is not False
    shaft_points = _arrow_shaft_points(points, main=main_arrow) if has_marker else points
    d = _path(shaft_points)
    label_x = label_y = 0
    if edge.get("labelPosition"):
        label_x = edge["labelPosition"]["x"]
        label_y = edge["labelPosition"]["y"]
    elif len(points) >= 2:
        longest = max(zip(points, points[1:]), key=lambda pair: abs(pair[0]["x"] - pair[1]["x"]) + abs(pair[0]["y"] - pair[1]["y"]))
        a, b = longest
        label_x = (a["x"] + b["x"]) / 2
        label_y = (a["y"] + b["y"]) / 2 - (10 if a["y"] == b["y"] else 2)
    label = "" if governance else _esc(edge.get("label", ""))
    compact_label = architecture or compact_label
    label_w = max(52, len(label) * (11 if compact_label else 15) + (10 if compact_label else 18))
    marker_id = _marker_id(color, main=main_arrow)
    marker = "" if not has_marker else f' marker-end="url(#{marker_id})"'
    arrow_geometry = ""
    if has_marker:
        tip, base = points[-1], shaft_points[-1]
        arrow_geometry = (f' data-arrow-shaft-x="{base["x"]:.1f}" data-arrow-shaft-y="{base["y"]:.1f}"'
                          f' data-arrow-tip-x="{tip["x"]:.1f}" data-arrow-tip-y="{tip["y"]:.1f}"')
    label_markup = "" if governance or not show_label or not label.strip() else (
        f'<g class="edge-label"><rect x="{label_x - label_w / 2:.1f}" y="{label_y - 13:.1f}" '
        f'width="{label_w}" height="22" rx="7" fill="#FFFFFF" fill-opacity=".94"/>'
        f'<text x="{label_x:.1f}" y="{label_y + 3:.1f}" text-anchor="middle">{label}</text></g>')
    group_class = "edge-group-arrow" if edge.get("groupArrow") else "edge"
    group_attr = (f' data-edge-group-arrow="{_esc(edge["edgeGroupId"])}"'
                  if edge.get("groupArrow") else "")
    relation_group_attr = (f' data-group-id="{_esc(edge["groupId"])}" '
                           f'data-group-pattern="{_esc(edge["groupPattern"])}"'
                           if edge.get("groupId") and edge.get("groupPattern") else "")
    return (f'<g class="{group_class}" data-edge="{_esc(edge["id"])}" data-from="{_esc(edge["from"])}" '
            f'data-to="{_esc(edge["to"])}" data-kind="{_esc(edge.get("kind", "other"))}" '
            f'data-layer-flow="{str(bool(edge.get("layerFlow"))).lower()}" '
            f'data-show-marker="{str(has_marker).lower()}"{arrow_geometry}{group_attr}{relation_group_attr}>'
            f'<path class="edge-line"{arrow_geometry} d="{d}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="butt"{dash}'
            f'{marker} vector-effect="non-scaling-stroke"/>{label_markup}</g>')


def _render_node(node: dict, position: dict, *, accent: str = "#3B82F6", include_drilldown: bool = True,
                 chain_number: int | None = None) -> str:
    x, y, w, h = position["x"], position["y"], position["width"], position["height"]
    title_lines = position.get("title_lines") or [node["title"]]
    desc_lines = position.get("desc_lines") or []
    route_annotation_lines = [str(line) for line in position.get("routeAnnotationLines", []) if str(line).strip()]
    compact = bool(position.get("compact"))
    title_line_height = 17 if compact else 23
    desc_line_height = 15 if compact else 18
    title_font_size = 14 if compact else 20
    title_height = len(title_lines) * title_line_height
    desc_height = len(desc_lines) * desc_line_height
    title_start = (FLOW_DETAIL_TITLE_BASELINE if compact and route_annotation_lines else
                   max(title_font_size + 2, (h - title_height - desc_height) / 2 + title_font_size)
                   if compact else max(35, (h - title_height - len(desc_lines) * 19) / 2 + 21))
    title_center = w / 2
    compact_class = " compact" if compact else ""
    card = (f'<rect class="node-card" x="0" y="0" width="{w}" height="{h}" rx="11" fill="#FFFFFF" '
            f'stroke="#CBD5E1" stroke-width="1.3" filter="url(#card-shadow)"/>'
            f'<rect x="1" y="5" width="4" height="{max(0, h - 10)}" rx="2" fill="{accent}"/>') if compact else (
            f'<rect class="node-card" x="0" y="0" width="{w}" height="{h}" rx="14" fill="#FFFFFF" '
            'stroke="#B7C7DB" stroke-width="1.5"/>')
    parts = [f'<g class="node{compact_class}" data-node="{_esc(node["id"])}" data-layer="{_esc(position.get("layer", node.get("layer", "")))}" '
             f'data-title="{_esc(node["title"])}" data-desc="{_esc(node.get("desc", ""))}" '
             f'transform="translate({x:.1f} {y:.1f})" tabindex="0" role="button">', card]
    for index, line in enumerate(title_lines):
        parts.append(f'<text class="node-title" x="{title_center}" y="{title_start + index * title_line_height:.1f}" text-anchor="middle">{_esc(line)}</text>')
    for index, line in enumerate(desc_lines):
        desc_baseline = (FLOW_DETAIL_DESC_BASELINE + index * desc_line_height
                         if compact and route_annotation_lines else
                         title_start + title_height + (3 if compact else 4) + index * desc_line_height)
        parts.append(f'<text class="node-desc" x="{w / 2}" y="{desc_baseline:.1f}" text-anchor="middle">{_esc(line)}</text>')
    if route_annotation_lines:
        for index, line in enumerate(route_annotation_lines):
            annotation_y = (FLOW_DETAIL_TAG_BASELINE + index * FLOW_DETAIL_TAG_LINE_HEIGHT
                            if compact else title_start + title_height + 4 + len(desc_lines) * desc_line_height + index * 12)
            parts.append(f'<text class="route-annotation" x="{w / 2}" y="{annotation_y:.1f}" text-anchor="middle">{_esc(line)}</text>')
    if chain_number:
        parts.append(f'<g class="chain-badge" data-chain-badge="{chain_number}" aria-label="主链路第{chain_number}步"><circle cx="0" cy="0" r="9"/>'
                     f'<text x="0" y="4" text-anchor="middle">{chain_number}</text></g>')
    if include_drilldown and node.get("drilldown"):
        parts.append(f'<g class="drill-icon" role="button" tabindex="0" aria-label="进入下钻图">'
                     f'<circle cx="{w - 16}" cy="16" r="8" fill="#F1F5F9" stroke="#CBD5E1"/>'
                     f'<path d="M {w - 19} 19 L {w - 13} 13 M {w - 18} 13 H {w - 13} V 18" '
                     'fill="none" stroke="#475569" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></g>')
    parts.append("</g>")
    return "".join(parts)


def _render_edge_groups(groups: list[dict], *, architecture: bool = False) -> str:
    parts = []
    for group in groups:
        governance = group.get("kind") == "governance"
        color = _edge_color({"kind": group.get("kind", "other"),
                             "groupPattern": group.get("pattern")}, architecture=architecture)
        dash = ' stroke-dasharray="5 5"' if governance else ""
        group_attrs = (f'data-edge-group="{_esc(group["id"])}" '
                       f'data-kind="{_esc(group.get("kind", "other"))}"')
        if group.get("pattern") == "fan_out":
            parts.append(f'<path class="edge-group-line" {group_attrs} d="{_path(group.get("trunkPoints", []))}" '
                         f'fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="butt"{dash} vector-effect="non-scaling-stroke"/>')
        elif group.get("pattern") == "fan_in":
            parts.append(f'<path class="edge-group-line" {group_attrs} d="{_path(group.get("busPoints", []))}" '
                         f'fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="butt"{dash} vector-effect="non-scaling-stroke"/>')
            arrow = {"id": group["id"] + "-arrow", "from": group["targetId"], "to": group["targetId"],
                     "points": group.get("targetArrowPoints", []), "kind": group.get("kind", "call"), "label": "", "main": False,
                     "strokeColor": color, "strokeWidth": 1.8,
                     "groupArrow": True, "edgeGroupId": group["id"]}
            parts.append(_render_edge(arrow, architecture=architecture, show_label=False))
        elif group.get("pattern") == "bidirectional":
            # Both directions are rendered by their evidence edge paths on distinct tracks.
            continue
    return "".join(parts)


def _render_relation_matrix_svg(diagram: dict, layout: dict) -> str:
    matrix = layout["matrix"]
    nodes = {node["id"]: node for node in diagram["nodes"]}
    positions = {position["id"]: position for position in layout["nodes"]}
    parts = [f'<text class="diagram-title" x="36" y="38">{_esc(diagram["title"])}</text>',
             f'<text class="matrix-axis" x="36" y="{matrix["y"] + matrix["headerHeight"] - 10}">调用方 ↓</text>',
             f'<text class="matrix-axis" x="{matrix["x"]}" y="{matrix["y"] - 14}">被调用方 →</text>']
    for cell in matrix["cells"]:
        cell_id = f'{cell["sourceId"]}::{cell["targetId"]}'
        parts.append(f'<g class="matrix-cell" data-relation-cell="{_esc(cell_id)}">'
                     f'<rect x="{cell["x"]}" y="{cell["y"]}" width="{cell["width"]}" height="{cell["height"]}" '
                     'fill="#FFFFFF" stroke="#CBD5E1" stroke-width="1"/>')
        if cell["edgeIds"]:
            labels = cell.get("labels", [])
            visible = labels[0] if len(labels) == 1 else f'{len(cell["edgeIds"])} 条关系'
            lines = wrap_text(visible, cell["width"] - 16, 12)
            if len(lines) > 2:
                visible = f'{len(cell["edgeIds"])} 条关系'
                lines = wrap_text(visible, cell["width"] - 16, 12)
            first_y = cell["y"] + (cell["height"] / 2) - (len(lines) - 1) * 7 + 4
            parts.append(f'<text x="{cell["x"] + cell["width"] / 2}" y="{first_y}" text-anchor="middle">'
                         + "".join(f'<tspan x="{cell["x"] + cell["width"] / 2}" dy="{0 if index == 0 else 14}">{_esc(line)}</tspan>'
                                  for index, line in enumerate(lines)) + "</text>")
        parts.append("</g>")
    for node_id, position in positions.items():
        node = nodes[node_id]
        x, y, width, height = position["x"], position["y"], position["width"], position["height"]
        parts.append(f'<g class="node matrix-node" data-node="{_esc(node_id)}" data-layer="{_esc(position["layer"])}" '
                     f'data-title="{_esc(node["title"])}" data-desc="{_esc(node.get("desc", ""))}" '
                     f'transform="translate({x} {y})" tabindex="0" role="button">'
                     f'<rect class="node-card" x="0" y="0" width="{width}" height="{height}" rx="8" fill="#EFF6FF" stroke="#93C5FD"/>'
                     f'<text class="node-title" x="{width / 2}" y="{height / 2 + 5}" text-anchor="middle" font-size="14">'
                     f'{_esc(node["title"])}</text></g>')
    legend_y = layout["height"] - 18
    parts.append(f'<circle data-legend-key="matrix" cx="44" cy="{legend_y - 4}" r="4" fill="#2563EB"/>'
                 f'<text class="matrix-axis" x="56" y="{legend_y}">有关系；空白表示无关系</text>')
    title = _esc(diagram["title"])
    return (f'<svg class="architecture-detail relation-matrix" data-view-mode="relation-matrix" '
            f'xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {layout["width"]} {layout["height"]}" '
            f'width="{layout["width"]}" height="{layout["height"]}" role="img" aria-label="{title}">'
            f'<defs><filter id="card-shadow"><feDropShadow dx="0" dy="1" stdDeviation="1" flood-color="#0f172a" flood-opacity=".08"/></filter></defs>'
            f'<style>{_SVG_STYLE}</style><rect width="100%" height="100%" fill="#F8FAFC"/>{"".join(parts)}</svg>')


def render_svg(diagram: dict, layout: dict, *, include_drilldown: bool | None = None) -> str:
    """将布局转成可被 draw.io/Figma/Inkscape 导入的纯 SVG。"""
    if layout.get("viewMode") == "relation_matrix":
        return _render_relation_matrix_svg(diagram, layout)
    architecture = diagram["type"] == "architecture"
    if architecture:
        if (not isinstance(diagram.get("layout"), dict)
                or diagram["layout"].get("contractVersion") != 2
                or layout.get("contractVersion") != 2):
            raise ValueError("架构主图必须使用布局契约 V2；旧版模块连线布局不可渲染")
        if diagram.get("edges") or any(not edge.get("layerFlow") for edge in layout.get("edges", [])):
            raise ValueError("架构主图只允许泳道边界间的层间通道；模块关系必须放入下钻图")
    architecture_detail = bool(layout.get("hardcodedPorts") and diagram["type"] == "flow")
    if include_drilldown is None:
        include_drilldown = True
    layer_ids = {item["id"]: i for i, item in enumerate(layout.get("layers", []))}
    body: list[str] = []
    for layer in layout.get("layers", []):
        body.append(_render_layer(layer, layer_ids[layer["id"]], architecture=architecture))
    for group in layout.get("groupFrames", []):
        body.append(f'<g class="group-frame" data-group="{_esc(group["id"])}">'
                    f'<rect x="{group["x"]:.1f}" y="{group["y"]:.1f}" width="{group["width"]:.1f}" '
                    f'height="{group["height"]:.1f}" rx="10" fill="#FFFFFF" fill-opacity=".4" '
                    f'stroke="#94A3B8" stroke-dasharray="4 4"/>'
                    f'<text x="{group["x"] + 8:.1f}" y="{group["y"] + 16:.1f}">{_esc(group["name"])}</text></g>')
    body.append(_render_edge_groups(layout.get("edgeGroups", []), architecture=architecture))
    for edge in layout.get("edges", []):
        body.append(_render_edge(edge, architecture=architecture, compact_label=architecture_detail,
                                 show_label=(not architecture and diagram.get("showEdgeLabels", True))
                                 and not edge.get("layerFlow") and edge.get("showLabel", True)))
    nodes_by_id = {node["id"]: node for node in diagram["nodes"]}
    layer_styles = {layer["id"]: _layer_style(layer, layer_ids[layer["id"]], architecture=architecture)
                    for layer in layout.get("layers", [])}
    for position in layout["nodes"]:
        accent = layer_styles.get(position.get("layer"), {}).get("stroke", "#3B82F6")
        body.append(_render_node(nodes_by_id[position["id"]], position, accent=accent,
                                 include_drilldown=include_drilldown,
                                 chain_number=position.get("chainOrder")))
    if layout.get("mainChain"):
        chain_text = "主链路：" + " → ".join(
            f'{("①", "②", "③", "④", "⑤", "⑥", "⑦")[item["number"] - 1]}{item["title"]}'
            for item in layout["mainChain"])
        body.append(f'<text class="main-chain" x="{PAD}" y="62">{_esc(chain_text)}</text>')
    if diagram["type"] == "sequence":
        for x in layout.get("lifelines", {}).values():
            body.append(f'<path class="lifeline" d="M {x:.1f} 135 L {x:.1f} {layout["height"] - 52}"/>')
        # 时序参与者位于上方，消息线和标签随后绘制，保证消息不被生命线遮盖。
        body = [item for item in body if 'class="lifeline"' not in item]
        lifelines = [f'<path class="lifeline" d="M {x:.1f} 135 L {x:.1f} {layout["height"] - 52}"/>'
                     for x in layout.get("lifelines", {}).values()]
        message_edges = [_render_edge(edge) for edge in layout.get("edges", [])]
        participant_nodes = [
            _render_node(node, next(pos for pos in layout["nodes"] if pos["id"] == node["id"]))
            for node in diagram["nodes"]
        ]
        body = lifelines + message_edges + participant_nodes
    if architecture and layout.get("contractVersion") == 2:
        body.append(_render_v2_legend(diagram, layout))
    else:
        body.append(_render_detail_legend(diagram, layout))
    title = _esc(diagram["title"])
    marker_specs = {
        (_edge_color(edge, architecture=architecture), architecture and bool(edge.get("layerFlow")))
        for edge in layout.get("edges", [])
        if edge.get("showMarker") is not False
    }
    marker_specs.update(
        (str(item["color"]), bool(item.get("mainMarker")))
        for item in _detail_legend_specs(diagram, layout) if item["marker"]
    )
    if architecture and layout.get("contractVersion") == 2:
        marker_specs.add(("#155EEF", True))
    marker_defs = "".join(_marker_definition(color, main=main) for color, main in sorted(marker_specs))
    svg_class = "architecture-diagram" if architecture else "architecture-detail" if architecture_detail else ""
    route_mode = ("architecture" if architecture else
                  "hardcoded-detail" if layout.get("hardcodedPorts") else "standard")
    return (f'<svg class="{svg_class}" data-renderer-version="{RENDERER_VERSION}" '
            f'data-layout-version="{LAYOUT_ALGORITHM_VERSION}" data-route-mode="{route_mode}" '
            f'data-direction="{_esc(diagram.get("direction", "TB"))}" '
            f'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'viewBox="0 0 {layout["width"]} {layout["height"]}" width="{layout["width"]}" height="{layout["height"]}" '
            f'role="img" aria-label="{title}"><defs><filter id="card-shadow" x="-10%" y="-10%" width="120%" height="130%">'
            f'<feDropShadow dx="0" dy="1" stdDeviation="1.3" flood-color="#0f172a" flood-opacity=".09"/></filter>'
            f'{marker_defs}</defs><style>{_SVG_STYLE}</style>'
            f'<rect width="100%" height="100%" fill="#F8FAFC"/><text class="diagram-title" x="{PAD}" y="38">{title}</text>'
            f'{"".join(body)}</svg>')


def _view_catalog(diagram: dict, backend: str = "auto", *, include_drilldown: bool | None = None,
                  architecture_detail: bool = False, root_layout: dict | None = None,
                  precomputed_layouts: dict[str, dict] | None = None) -> dict[str, dict]:
    result: dict[str, dict] = {}
    def visit(current: dict, inherited_architecture: bool = False) -> None:
        architecture_context = inherited_architecture or current["type"] == "architecture"
        hardcoded_ports = architecture_context and current["type"] == "flow"
        layout_backend = "builtin" if hardcoded_ports else backend
        layout = (root_layout if current is diagram and root_layout is not None else
                  (precomputed_layouts or {}).get(current.get("id")))
        if layout is None:
            layout = layout_diagram(current, backend=layout_backend, hardcoded_ports=hardcoded_ports)
        drilldown = include_drilldown if current["type"] == "architecture" else None
        canonical = json.dumps({"algorithm": LAYOUT_ALGORITHM_VERSION, "diagram": current},
                               ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        layout_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        result[current["id"]] = {"diagram": current, "layout": layout,
                                 "svg": render_svg(current, layout, include_drilldown=drilldown),
                                 "hardcodedPorts": hardcoded_ports, "layoutHash": layout_hash}
        for child in current.get("subDiagrams", []):
            visit(child, architecture_context)
    visit(diagram, architecture_detail)
    return result


_HTML_STYLE = r"""
*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;font-family:"Microsoft YaHei","Noto Sans CJK SC",sans-serif;color:#0f172a;background:#f8fafc}
body{display:flex;flex-direction:column}.toolbar{display:flex;gap:8px;align-items:center;padding:10px 14px;background:#fff;border-bottom:1px solid #e2e8f0;flex-wrap:wrap;position:sticky;top:0;z-index:3}
button{font:inherit;font-size:13px;border:1px solid #cbd5e1;background:#fff;color:#334155;border-radius:8px;padding:7px 11px;cursor:pointer}button:hover{background:#f1f5f9}button.active{background:#155eef;color:#fff;border-color:#155eef}
#crumb{font-size:13px;color:#475569;margin-left:8px}.workspace{position:relative;overflow:auto;flex:1;padding:18px}#canvas{min-width:min-content;min-height:100%;display:flex;justify-content:center;align-items:flex-start}#canvas svg{max-width:none;height:auto;box-shadow:0 6px 28px #0f172a12;border-radius:12px;background:#f8fafc}
.diagram-title{font-size:20px;font-weight:700;fill:#0f172a}.layer-title{font-size:20px;font-weight:700;fill:#183153}.layer-desc{font-size:13px;fill:#64748b}.node-title{font-size:20px;font-weight:700;fill:#163354}.node-desc{font-size:13px;fill:#52657e}.drill{font-size:13px;fill:#4338ca}.edge-label text{font-size:13px;fill:#475569}.architecture-diagram .layer-title{font-size:17px}.architecture-diagram .compact .node-title{font-size:15px}.architecture-diagram .compact .node-desc{font-size:12px}.architecture-diagram .compact .drill{font-size:10px}.architecture-diagram .edge-label text,.architecture-detail .edge-label text{font-size:11px}.drill-icon{cursor:pointer}.node{cursor:pointer;outline:none}.node.selected .node-card{stroke:#155eef;stroke-width:3}.node.dim,.edge.dim{opacity:.16}.node.highlight .node-card{stroke:#2563eb;stroke-width:2.5}.edge-line{stroke-linejoin:round;stroke-linecap:butt}.edge-label rect{stroke:#e2e8f0;stroke-width:.6}.lifeline{stroke:#94a3b8;stroke-width:1.4;stroke-dasharray:5 6}.node.dragging{cursor:grabbing}
#details{position:fixed;right:18px;bottom:18px;z-index:4;width:300px;max-height:80vh;overflow:auto;background:#fff;border:1px solid #cbd5e1;border-radius:12px;padding:14px;box-shadow:0 10px 32px #0f172a22;display:none}#details.show{display:block}#detailTitle{font-weight:700;margin-bottom:10px}#detailDesc,#detailInputs,#detailOutputs,#detailEvidence{font-size:13px;color:#475569;line-height:1.6;overflow-wrap:anywhere}.detail-label{font-size:11px;font-weight:700;color:#64748b;margin-top:10px}#detailStatus{font-size:12px;color:#64748b;margin-top:8px}#detailLayer{margin-top:6px;width:100%;padding:6px;border:1px solid #cbd5e1;border-radius:6px}
.edge.selected .edge-line{stroke-width:4}.crumb{cursor:pointer;color:#155eef!important}.route-annotation{font-size:10px;fill:#475569}
@media(max-width:700px){.toolbar{gap:5px;padding:8px}.workspace{padding:8px}button{padding:6px 8px;font-size:12px}}
"""


_ARCHITECTURE_HTML_SCRIPT = r"""
const payload=JSON.parse(document.getElementById('payload').textContent);
const canvas=document.getElementById('canvas'),workspace=document.querySelector('.workspace'),backButton=document.getElementById('back'),detailPanel=document.getElementById('module-details'),notice=document.getElementById('layout-notice');
let currentId=payload.root,history=[],graph=null,svg=null,hardcodedPorts=false,nodeEls=[],nodes=new Map(),layers=new Map(),initial=new Map(),storageKey='',drag=null,routeFrame=0,suppressClick=false;

function readPosition(el){
  const matrix=el.transform.baseVal.consolidate()?.matrix;
  return {x:Number(matrix?.e||0),y:Number(matrix?.f||0)};
}
function pointerInSvg(event){const point=svg.createSVGPoint();point.x=event.clientX;point.y=event.clientY;return point.matrixTransform(svg.getScreenCTM().inverse())}
let noticeTimer=0;
function showNotice(message){if(!notice)return;notice.textContent=message;notice.hidden=false;clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>{notice.hidden=true},4200)}
function boxOf(el){
  const p=readPosition(el),card=el.querySelector('.node-card');
  return {id:el.dataset.node,layer:el.dataset.layer,x:p.x,y:p.y,
    w:Number(card.getAttribute('width')),h:Number(card.getAttribute('height'))};
}
function clamp(value,min,max){return Math.max(min,Math.min(max,value))}
function nearestFreePosition(el,x,y){
  const lane=svg.querySelector(`.layer[data-layer="${CSS.escape(el.dataset.layer)}"] rect`),self=boxOf(el);
  if(!lane)return {x,y};
  const lx=Number(lane.getAttribute('x')),ly=Number(lane.getAttribute('y')),lw=Number(lane.getAttribute('width')),lh=Number(lane.getAttribute('height'));
  // Match the V2 lane's fixed 58px header, 8px content inset, and 8px bottom inset.
  // The previous 64px/12px bounds excluded auto-laid-out cards by 2-4px and
  // caused a small downward drag to jump upward to the nearest legal position.
  const minX=lx+14,maxX=lx+lw-self.w-14,minY=ly+66,maxY=ly+lh-self.h-8;
  const desired={x:clamp(x,minX,maxX),y:clamp(y,minY,maxY)};
  const peers=nodeEls.map(boxOf).filter(box=>box.id!==self.id&&box.layer===self.layer),gap=10;
  const pairGap=peer=>{
    const labels=graph.edges.filter(edge=>(edge.from===self.id&&edge.to===peer.id)||(edge.to===self.id&&edge.from===peer.id)).map(edge=>Math.max(52,[...edge.label].length*11+10)+4);
    return labels.length?Math.max(...labels):gap;
  };
  const xs=new Set([desired.x,minX,maxX]),ys=new Set([desired.y,minY,maxY]);
  for(const peer of peers){const separation=pairGap(peer);xs.add(clamp(peer.x-self.w-separation,minX,maxX));xs.add(clamp(peer.x+peer.w+separation,minX,maxX));ys.add(clamp(peer.y-self.h-gap,minY,maxY));ys.add(clamp(peer.y+peer.h+gap,minY,maxY))}
  const candidates=[];for(const cx of xs)for(const cy of ys){
    if(peers.some(peer=>cx<peer.x+peer.w+pairGap(peer)&&cx+self.w>peer.x-pairGap(peer)&&cy<peer.y+peer.h+gap&&cy+self.h>peer.y-gap))continue;
    candidates.push({x:cx,y:cy,distance:(cx-desired.x)**2+(cy-desired.y)**2});
  }
  candidates.sort((a,b)=>a.distance-b.distance);
  return candidates[0]||readPosition(el);
}
function compactPoints(points){
  const out=[];
  for(const point of points){
    const previous=out.at(-1);
    if(previous&&previous.x===point.x&&previous.y===point.y)continue;
    if(out.length>1){const before=out.at(-2);if((before.x===previous.x&&previous.x===point.x)||(before.y===previous.y&&previous.y===point.y))out.pop()}
    out.push(point);
  }
  return out;
}
function segmentHitsBox(a,b,box,pad=4){
  const left=box.x-pad,right=box.x+box.w+pad,top=box.y-pad,bottom=box.y+box.h+pad;
  if(a.y===b.y)return a.y>top&&a.y<bottom&&Math.max(Math.min(a.x,b.x),left)<Math.min(Math.max(a.x,b.x),right);
  if(a.x===b.x)return a.x>left&&a.x<right&&Math.max(Math.min(a.y,b.y),top)<Math.min(Math.max(a.y,b.y),bottom);
  return true;
}
function routeCrossPenalty(points,routes){
  let penalty=0;
  for(let i=1;i<points.length;i++)for(const route of routes)for(let j=1;j<route.length;j++){
    const a=points[i-1],b=points[i],c=route[j-1],d=route[j];
    const ah=a.y===b.y,bh=c.y===d.y;
    if(ah!==bh){const h=ah?[a,b]:[c,d],v=ah?[c,d]:[a,b];
      if(Math.min(h[0].x,h[1].x)<v[0].x&&v[0].x<Math.max(h[0].x,h[1].x)&&Math.min(v[0].y,v[1].y)<h[0].y&&h[0].y<Math.max(v[0].y,v[1].y))penalty+=260;
    }else if(ah&&a.y===c.y){const overlap=Math.min(Math.max(a.x,b.x),Math.max(c.x,d.x))-Math.max(Math.min(a.x,b.x),Math.min(c.x,d.x));if(overlap>8)penalty+=Math.min(180,overlap*2)}
    else if(!ah&&a.x===c.x){const overlap=Math.min(Math.max(a.y,b.y),Math.max(c.y,d.y))-Math.max(Math.min(a.y,b.y),Math.min(c.y,d.y));if(overlap>8)penalty+=Math.min(180,overlap*2)}
  }
  return penalty;
}
function routeScore(points,obstacles,routes){
  let score=(points.length-2)*28;
  for(let i=1;i<points.length;i++){
    const a=points[i-1],b=points[i];score+=(Math.abs(a.x-b.x)+Math.abs(a.y-b.y))*.04;
    for(const box of obstacles)if(segmentHitsBox(a,b,box))score+=100000;
  }
  return score+routeCrossPenalty(points,routes);
}
const ARCH_EDGE_OUTSET=16;
function hardcodedHorizontal(a,b,direction){
  const dx=Math.abs((b.x+b.w/2)-(a.x+a.w/2)),dy=Math.abs((b.y+b.h/2)-(a.y+a.h/2));
  return dx===dy?direction==='LR':dx>dy;
}
function architectureRoute(a,b,obstacles,routes,horizontalOverride=null){
  const ax=a.x+a.w/2,ay=a.y+a.h/2,bx=b.x+b.w/2,by=b.y+b.h/2;
  let start,end,startOut,endOut,candidates;
  const horizontal=horizontalOverride===null?a.layer===b.layer:horizontalOverride;
  if(horizontal){
    const right=bx>=ax,sign=right?1:-1;
    start={x:right?a.x+a.w:a.x,y:ay};end={x:right?b.x:b.x+b.w,y:by};
    startOut={x:start.x+sign*ARCH_EDGE_OUTSET,y:start.y};endOut={x:end.x-sign*ARCH_EDGE_OUTSET,y:end.y};
    candidates=[
      [start,startOut,{x:endOut.x,y:startOut.y},endOut,end],
      [start,startOut,{x:startOut.x,y:endOut.y},endOut,end]
    ];
  }else{
    const down=by>=ay,sign=down?1:-1;
    start={x:ax,y:down?a.y+a.h:a.y};end={x:bx,y:down?b.y:b.y+b.h};
    startOut={x:start.x,y:start.y+sign*ARCH_EDGE_OUTSET};endOut={x:end.x,y:end.y-sign*ARCH_EDGE_OUTSET};
    candidates=[
      [start,startOut,{x:startOut.x,y:endOut.y},endOut,end],
      [start,startOut,{x:endOut.x,y:startOut.y},endOut,end]
    ];
  }
  return candidates.map(compactPoints).map((points,index)=>({points,index,score:routeScore(points,obstacles,routes)}))
    .sort((left,right)=>left.score-right.score||left.index-right.index)[0].points;
}
function arrowShaftPoints(points,main=false){
  const result=points.map(point=>({...point}));
  if(result.length<2)throw new Error('带箭头的连线至少需要两个路径点');
  const length=main?18:12,tip=result.at(-1),previous=result.at(-2),dx=tip.x-previous.x,dy=tip.y-previous.y,segmentLength=Math.hypot(dx,dy);
  if(segmentLength+1e-6<length)throw new Error(`箭头末段 ${segmentLength.toFixed(1)}px 短于箭头长度 ${length}px`);
  result[result.length-1]={x:tip.x-dx/segmentLength*length,y:tip.y-dy/segmentLength*length};
  return result;
}
function setArrowShaftPath(group,points){
  const marked=group.dataset.showMarker!=='false',main=group.dataset.layerFlow==='true',shaft=marked?arrowShaftPoints(points,main):points;
  const line=group.querySelector('.edge-line');line.setAttribute('d','M '+shaft.map(point=>`${point.x} ${point.y}`).join(' L '));
  if(marked){const tip=points.at(-1),base=shaft.at(-1);for(const element of [group,line]){element.dataset.arrowTipX=String(tip.x);element.dataset.arrowTipY=String(tip.y);element.dataset.arrowShaftX=String(base.x);element.dataset.arrowShaftY=String(base.y)}}
  group._routePoints=points;
}
function orthogonalRoute(a,b,vertical,obstacles,routes){
  const ax=a.x+a.w/2,ay=a.y+a.h/2,bx=b.x+b.w/2,by=b.y+b.h/2;
  if(vertical){
    const down=by>=ay,start={x:ax,y:down?a.y+a.h:a.y},end={x:bx,y:down?b.y+b.h:b.y};
    if(start.x===end.x)return [start,end];
    const tracks=new Set([(start.x+end.x)/2,start.x-22,start.x+22,end.x-22,end.x+22]);
    for(const box of obstacles)for(const x of [box.x-14,box.x+box.w+14])tracks.add(x);
    const candidates=[[start,{x:end.x,y:start.y},end],[start,{x:start.x,y:end.y},end]];
    for(const x of tracks)candidates.push([start,{x,y:start.y},{x,y:end.y},end]);
    const clean=candidates.map(compactPoints).sort((left,right)=>routeScore(left,obstacles,routes)-routeScore(right,obstacles,routes));
    return clean[0];
  }
  const right=bx>=ax,start={x:right?a.x+a.w:a.x,y:ay},end={x:right?b.x:b.x+b.w,y:by};
  if(start.y===end.y)return [start,end];
  const tracks=new Set([(start.y+end.y)/2,start.y-20,start.y+20,end.y-20,end.y+20]);
  for(const box of obstacles)for(const y of [box.y-14,box.y+box.h+14])tracks.add(y);
  const candidates=[[start,{x:end.x,y:start.y},end],[start,{x:start.x,y:end.y},end]];
  for(const y of tracks)candidates.push([start,{x:start.x,y},{x:end.x,y},end]);
  const clean=candidates.map(compactPoints).sort((left,right)=>routeScore(left,obstacles,routes)-routeScore(right,obstacles,routes));
  return clean[0];
}
function overlaps(a,b,gap=4){return a.x<b.x+b.w+gap&&a.x+a.w>b.x-gap&&a.y<b.y+b.h+gap&&a.y+a.h>b.y-gap}
function labelHitsRoute(box,points,pad=3){
  for(let i=1;i<points.length;i++){
    const a=points[i-1],b=points[i];
    if(a.y===b.y){if(a.y>=box.y-pad&&a.y<=box.y+box.h+pad&&Math.max(Math.min(a.x,b.x),box.x-pad)<Math.min(Math.max(a.x,b.x),box.x+box.w+pad))return true}
    else if(a.x===b.x){if(a.x>=box.x-pad&&a.x<=box.x+box.w+pad&&Math.max(Math.min(a.y,b.y),box.y-pad)<Math.min(Math.max(a.y,b.y),box.y+box.h+pad))return true}
  }
  return false;
}
function placeLabel(group,points,allBoxes,placed,allRoutes,boxMap){
  const label=group.querySelector('.edge-label');if(!label)return;
  const rect=label.querySelector('rect'),text=label.querySelector('text'),bounds=text.getBBox();
  const architectureRouting=graph.type==='architecture'||hardcodedPorts;
  const width=Math.max(52,bounds.width+(architectureRouting?10:18)),height=22;
  const segments=points.slice(1).map((end,index)=>({start:points[index],end,length:Math.abs(end.x-points[index].x)+Math.abs(end.y-points[index].y)})).sort((a,b)=>b.length-a.length);
  if(architectureRouting){
    const source=boxMap.get(group.dataset.from),target=boxMap.get(group.dataset.to);
    const candidates=[];
    const horizontal=graph.type==='architecture'?source.layer===target.layer:hardcodedHorizontal(source,target,graph.direction);
    const first=points[0],last=points.at(-1);
    if(horizontal&&Math.abs(first.y-last.y)<=12)candidates.push({x:(first.x+last.x)/2,y:(first.y+last.y)/2-14});
    if(!horizontal&&Math.abs(first.x-last.x)<=12)candidates.push({x:(first.x+last.x)/2+Math.max(32,width/2+6),y:(first.y+last.y)/2});
    const horizontalSegments=segments.filter(({start,end})=>start.y===end.y);
    const verticalSegments=segments.filter(({start,end})=>start.x===end.x);
    const orderedSegments=graph.direction==='LR'?[...verticalSegments,...horizontalSegments]:[...horizontalSegments,...verticalSegments];
    for(const segment of orderedSegments){
      const {start,end}=segment,mx=(start.x+end.x)/2,my=(start.y+end.y)/2;
      if(start.y===end.y)candidates.push({x:mx,y:start.y-14},{x:mx,y:start.y+14});
      if(start.x===end.x){
        const side=target.x+target.w/2>=source.x+source.w/2?1:-1;
        candidates.push({x:start.x+side*(width/2+6),y:my},{x:start.x-side*(width/2+6),y:my});
      }
    }
    const view=svg.viewBox.baseVal,otherRoutes=allRoutes.filter(route=>route!==points);
    const valid=candidates.find(point=>{
      const box={x:point.x-width/2,y:point.y-height/2,w:width,h:height};
      if(box.x<view.x+4||box.y<view.y+4||box.x+width>view.x+view.width-4||box.y+height>view.y+view.height-4)return false;
      if(allBoxes.some(item=>overlaps(box,item,3))||placed.some(item=>overlaps(box,item,3)))return false;
      return !otherRoutes.some(route=>labelHitsRoute(box,route,2));
    })||candidates[0];
    if(!valid)return;
    rect.setAttribute('x',valid.x-width/2);rect.setAttribute('y',valid.y-height/2);rect.setAttribute('width',width);rect.setAttribute('height',height);
    text.setAttribute('x',valid.x);text.setAttribute('y',valid.y+4);
    placed.push({x:valid.x-width/2,y:valid.y-height/2,w:width,h:height});return;
  }
  const candidates=[];
  for(const segment of segments){const {start,end}=segment,mx=(start.x+end.x)/2,my=(start.y+end.y)/2;
    if(start.y===end.y){candidates.push({x:mx,y:my-16},{x:mx,y:my+16})}
    else candidates.push({x:mx-width/2-9,y:my},{x:mx+width/2+9,y:my});
  }
  const source=boxMap.get(group.dataset.from),target=boxMap.get(group.dataset.to),edgeX=((source.x+source.w/2)+(target.x+target.w/2))/2;
  const edgeY=((source.y+source.h/2)+(target.y+target.h/2))/2;
  const ySlots=new Set();
  for(const box of allBoxes){ySlots.add(box.y-height/2-7);ySlots.add(box.y+box.h+height/2+7)}
  for(const point of points){ySlots.add(point.y-height/2-7);ySlots.add(point.y+height/2+7)}
  const xSlots=new Set([edgeX]);
  for(const segment of segments){xSlots.add((segment.start.x+segment.end.x)/2);if(segment.start.x===segment.end.x){xSlots.add(segment.start.x-width/2-10);xSlots.add(segment.start.x+width/2+10)}}
  const nearby=[...xSlots].flatMap(x=>[...ySlots].map(y=>({x,y})));
  nearby.sort((a,b)=>(Math.abs(a.x-edgeX)+Math.abs(a.y-edgeY))-(Math.abs(b.x-edgeX)+Math.abs(b.y-edgeY)));
  candidates.push(...nearby);
  const view=svg.viewBox.baseVal;
  const valid=candidates.find(point=>{
    const labelBox={x:point.x-width/2,y:point.y-height/2,w:width,h:height};
    if(labelBox.x<view.x+4||labelBox.y<view.y+4||labelBox.x+width>view.x+view.width-4||labelBox.y+height>view.y+view.height-4)return false;
    if(allBoxes.some(box=>overlaps(labelBox,box,3)))return false;
    if(placed.some(box=>overlaps(labelBox,box,3)))return false;
    return !allRoutes.some(route=>labelHitsRoute(labelBox,route,4));
  })||candidates.find(point=>point.x>=view.x+width/2&&point.x<=view.x+view.width-width/2&&point.y>=view.y+height/2&&point.y<=view.y+view.height-height/2)||candidates[0];
  rect.setAttribute('x',valid.x-width/2);rect.setAttribute('y',valid.y-height/2);rect.setAttribute('width',width);rect.setAttribute('height',height);
  text.setAttribute('x',valid.x);text.setAttribute('y',valid.y+4);
  placed.push({x:valid.x-width/2,y:valid.y-height/2,w:width,h:height});
}
function updateGroupedEdges(boxes){
  const edgeById=new Map(graph.edges.map(edge=>[edge.id,edge]));
  const nodeById=new Map(graph.nodes.map(node=>[node.id,node]));
  const dPath=points=>'M '+points.map(point=>`${point.x} ${point.y}`).join(' L ');
  const write=(id,points)=>{const g=svg.querySelector(`[data-edge="${CSS.escape(id)}"]`);if(!g)return;setArrowShaftPath(g,points)};
  const compact=points=>{const out=[];for(const point of points){const prev=out.at(-1);if(prev&&prev.x===point.x&&prev.y===point.y)continue;if(out.length>1){const before=out.at(-2),vertical=before.x===prev.x&&prev.x===point.x&&Math.min(before.y,point.y)<=prev.y&&prev.y<=Math.max(before.y,point.y),horizontal=before.y===prev.y&&prev.y===point.y&&Math.min(before.x,point.x)<=prev.x&&prev.x<=Math.max(before.x,point.x);if(vertical||horizontal)out.pop()}out.push(point)}return out};
  const laneBox=id=>{const group=svg.querySelector(`.layer[data-layer="${CSS.escape(id)}"]`),rect=group?.querySelector('rect');if(!rect)return null;return{x:Number(rect.getAttribute('x')),y:Number(rect.getAttribute('y')),w:Number(rect.getAttribute('width')),h:Number(rect.getAttribute('height'))}};
  const channelMidpoint=(sourceLayerId,targetLayerId,horizontal)=>{const source=laneBox(sourceLayerId),target=laneBox(targetLayerId);if(!source||!target)return null;let start,end,crossStart,crossEnd,axisStart,axisEnd;if(horizontal){start=source.x+source.w;end=target.x;crossStart=source.y;crossEnd=source.y+source.h}else{start=source.y+source.h;end=target.y;crossStart=source.x;crossEnd=source.x+source.w}if(end<=start)return null;const blocked=[...svg.querySelectorAll('.layer[data-layer]')].some(group=>{if([sourceLayerId,targetLayerId].includes(group.dataset.layer))return false;const rect=group.querySelector('rect');if(!rect)return false;const box={x:Number(rect.getAttribute('x')),y:Number(rect.getAttribute('y')),w:Number(rect.getAttribute('width')),h:Number(rect.getAttribute('height'))};return horizontal?box.x<end&&box.x+box.w>start&&box.y<crossEnd&&box.y+box.h>crossStart:box.y<end&&box.y+box.h>start&&box.x<crossEnd&&box.x+box.w>crossStart});return blocked?null:(start+end)/2};
  for(const group of graph.edgeGroups||[]){
    const members=(group.edgeIds||[]).map(id=>edgeById.get(id)).filter(Boolean),pattern=group.pattern;
    if(!members.length||!['fan_out','fan_in','bidirectional'].includes(pattern))continue;
    const lr=graph.direction==='LR';
    if(pattern==='fan_out'){
      const source=boxes.get(group.sourceId),targets=members.map(edge=>boxes.get(edge.to)).filter(Boolean);if(!source||targets.length!==members.length)continue;
      const sourceNode=nodeById.get(group.sourceId),targetNode=nodeById.get(members[0].to);
      if(lr){const start={x:source.x+source.w,y:source.y+source.h/2},left=Math.min(...targets.map(box=>box.x)),channel=members.length>=3?channelMidpoint(sourceNode?.layer,targetNode?.layer,true):null,busX=channel??Math.min(left-20,start.x+24),ys=targets.map(box=>box.y+box.h/2);const trunk=compact([start,{x:busX,y:start.y},{x:busX,y:Math.min(...ys,start.y)},{x:busX,y:Math.max(...ys,start.y)}]);const path=svg.querySelector(`[data-edge-group="${CSS.escape(group.id)}"]`);if(path)path.setAttribute('d',dPath(trunk));for(const edge of members){const target=boxes.get(edge.to),y=target.y+target.h/2;write(edge.id,[{x:busX,y},{x:target.x,y}])}}
      else{const start={x:source.x+source.w/2,y:source.y+source.h},top=Math.min(...targets.map(box=>box.y)),channel=members.length>=3?channelMidpoint(sourceNode?.layer,targetNode?.layer,false):null,busY=channel??Math.min(top-20,start.y+24),xs=targets.map(box=>box.x+box.w/2),trunk=compact([start,{x:start.x,y:busY},{x:Math.min(...xs),y:busY},{x:Math.max(...xs),y:busY}]);const path=svg.querySelector(`[data-edge-group="${CSS.escape(group.id)}"]`);if(path)path.setAttribute('d',dPath(trunk));for(const edge of members){const target=boxes.get(edge.to),x=target.x+target.w/2;write(edge.id,[{x,y:busY},{x,y:target.y}])}}
    }else if(pattern==='fan_in'){
      const target=boxes.get(group.targetId),sources=members.map(edge=>boxes.get(edge.from)).filter(Boolean);if(!target||sources.length!==members.length)continue;
      const targetNode=nodeById.get(group.targetId),sourceNode=nodeById.get(members[0].from);
      if(lr){const end={x:target.x,y:target.y+target.h/2},right=Math.max(...sources.map(box=>box.x+box.w)),channel=members.length>=3?channelMidpoint(sourceNode?.layer,targetNode?.layer,true):null,busX=channel??(end.x-right<44?(right+end.x)/2:Math.max(right+20,end.x-24)),ys=sources.map(box=>box.y+box.h/2);const bus=[{x:busX,y:Math.min(...ys,end.y)},{x:busX,y:Math.max(...ys,end.y)}],busPath=svg.querySelector(`[data-edge-group="${CSS.escape(group.id)}"]`);if(busPath)busPath.setAttribute('d',dPath(bus));for(const edge of members){const source=boxes.get(edge.from);write(edge.id,[{x:source.x+source.w,y:source.y+source.h/2},{x:busX,y:source.y+source.h/2}])}const arrow=svg.querySelector(`[data-edge-group-arrow="${CSS.escape(group.id)}"]`);if(arrow)setArrowShaftPath(arrow,[{x:busX,y:end.y},end])}
      else{const end={x:target.x+target.w/2,y:target.y},bottom=Math.max(...sources.map(box=>box.y+box.h)),channel=members.length>=3?channelMidpoint(sourceNode?.layer,targetNode?.layer,false):null,busY=channel??(end.y-bottom<44?(bottom+end.y)/2:Math.max(bottom+20,end.y-24)),xs=sources.map(box=>box.x+box.w/2),bus=[{x:Math.min(...xs,end.x),y:busY},{x:Math.max(...xs,end.x),y:busY}],busPath=svg.querySelector(`[data-edge-group="${CSS.escape(group.id)}"]`);if(busPath)busPath.setAttribute('d',dPath(bus));for(const edge of members){const source=boxes.get(edge.from),x=source.x+source.w/2;write(edge.id,[{x,y:source.y+source.h},{x,y:busY}])}const arrow=svg.querySelector(`[data-edge-group-arrow="${CSS.escape(group.id)}"]`);if(arrow)setArrowShaftPath(arrow,[{x:end.x,y:busY},end])}
    }else{
      const forward=edgeById.get(group.forwardEdgeId);if(!forward)continue;
      for(const edge of members){const a=boxes.get(edge.from),b=boxes.get(edge.to);if(!a||!b)continue;const returning=edge.id===group.returnEdgeId;
        if(lr){const right=b.x+b.w/2>=a.x+a.w/2,mid=a.y+a.h/2,sign=right?1:-1,start={x:right?a.x+a.w:a.x,y:mid},end={x:right?b.x:b.x+b.w,y:b.y+b.h/2},outStart={x:start.x+sign*16,y:start.y},outEnd={x:end.x-sign*16,y:end.y},track=mid+(returning?12:-12);write(edge.id,compact([start,outStart,{x:outStart.x,y:track},{x:outEnd.x,y:track},outEnd,end]))}
        else{const down=b.y+b.h/2>=a.y+a.h/2,mid=a.x+a.w/2,sign=down?1:-1,start={x:mid,y:down?a.y+a.h:a.y},end={x:b.x+b.w/2,y:down?b.y:b.y+b.h},outStart={x:start.x,y:start.y+sign*16},outEnd={x:end.x,y:end.y-sign*16},track=mid+(returning?12:-12);write(edge.id,compact([start,outStart,{x:track,y:outStart.y},{x:track,y:outEnd.y},outEnd,end]))}
      }
    }
  }
}
function updateEdges(){
  routeFrame=0;
  const boxes=new Map(nodeEls.map(el=>[el.dataset.node,boxOf(el)])),allBoxes=[...boxes.values()],routes=[];
  const groupedIds=new Set((graph.edgeGroups||[]).filter(group=>['fan_out','fan_in','bidirectional'].includes(group.pattern)).flatMap(group=>group.edgeIds||[]));
  for(const edge of graph.edges){
    if(edge.layerFlow||graph.type==='sequence'||(graph.type==='architecture'&&!edge.layerFlow)||groupedIds.has(edge.id))continue;
    const source=boxes.get(edge.from),target=boxes.get(edge.to),group=svg.querySelector(`[data-edge="${CSS.escape(edge.id)}"]`);
    if(!source||!target||!group)continue;
    const obstacles=allBoxes.filter(box=>box.id!==source.id&&box.id!==target.id);
    const points=hardcodedPorts
      ?architectureRoute(source,target,obstacles,routes,hardcodedHorizontal(source,target,graph.direction))
      :orthogonalRoute(source,target,graph.direction!=='LR',obstacles,routes);
    setArrowShaftPath(group,points);
    group.dataset.startX=points[0].x;group.dataset.startY=points[0].y;group.dataset.endX=points.at(-1).x;group.dataset.endY=points.at(-1).y;
    routes.push(points);group._routePoints=points;
  }
  updateGroupedEdges(boxes);
  for(const edge of graph.edges){const group=svg.querySelector(`[data-edge="${CSS.escape(edge.id)}"]`);if(group?._routePoints)routes.push(group._routePoints)}
  const placed=[];
  for(const edge of graph.edges){if(edge.layerFlow||edge.showLabel===false)continue;const group=svg.querySelector(`[data-edge="${CSS.escape(edge.id)}"]`);if(group?._routePoints)placeLabel(group,group._routePoints,allBoxes,placed,routes,boxes)}
}
function scheduleRoutes(){if(!routeFrame)routeFrame=requestAnimationFrame(updateEdges)}
function persist(){try{const positions={};for(const el of nodeEls){const point=readPosition(el),base=initial.get(el.dataset.node);if(base)positions[el.dataset.node]={dx:Number((point.x-base.x).toFixed(3)),dy:Number((point.y-base.y).toFixed(3))}}localStorage.setItem(storageKey,JSON.stringify({layoutHash:payload.views[currentId].layoutHash,positions}))}catch(_){}}
function setPosition(el,point){el.setAttribute('transform',`translate(${point.x} ${point.y})`);el.dataset.x=String(point.x);el.dataset.y=String(point.y)}
function auditSavedLayout(){
  const boxes=nodeEls.map(boxOf),view=svg.viewBox.baseVal;
  for(const box of boxes)if(box.x<0||box.y<0||box.x+box.w>view.width||box.y+box.h>view.height)return 'canvas-boundary';
  for(let i=0;i<boxes.length;i++)for(let j=i+1;j<boxes.length;j++){
    const a=boxes[i],b=boxes[j];if(a.x<b.x+b.w&&a.x+a.w>b.x&&a.y<b.y+b.h&&a.y+a.h>b.y)return 'node-overlap';
  }
  const segmentHits=(a,b,r)=>a.y===b.y
    ?r.y<a.y&&a.y<r.y+r.h&&Math.max(Math.min(a.x,b.x),r.x)<Math.min(Math.max(a.x,b.x),r.x+r.w)
    :a.x===b.x&&r.x<a.x&&a.x<r.x+r.w&&Math.max(Math.min(a.y,b.y),r.y)<Math.min(Math.max(a.y,b.y),r.y+r.h);
  for(const edge of graph.edges){const group=svg.querySelector(`[data-edge="${CSS.escape(edge.id)}"]`),points=group?._routePoints||[];
    for(const box of boxes)if(box.id!==edge.from&&box.id!==edge.to)for(let i=0;i+1<points.length;i++)if(segmentHits(points[i],points[i+1],box))return 'edge-through-node';
  }
  return '';
}
function attachNodes(){
  for(const el of nodeEls){
    el.addEventListener('pointerdown',event=>{
      if(event.target.closest('.drill-icon')||event.button!==0||graph.type==='sequence')return;event.stopPropagation();el.setPointerCapture(event.pointerId);el.classList.add('dragging');
      const p=readPosition(el),start=pointerInSvg(event);drag={el,startX:start.x,startY:start.y,x:p.x,y:p.y,moved:false};
    });
    el.addEventListener('pointermove',event=>{
      if(!drag||drag.el!==el)return;
      const point=pointerInSvg(event),dx=point.x-drag.startX,dy=point.y-drag.startY;if(Math.abs(dx)+Math.abs(dy)>3)drag.moved=true;
      const x=drag.x+dx,y=drag.y+dy;
      setPosition(el,nearestFreePosition(el,x,y));scheduleRoutes();
    });
    const finish=()=>{if(drag?.el!==el)return;const moved=drag.moved;el.classList.remove('dragging');drag=null;persist();scheduleRoutes();if(moved){suppressClick=true;setTimeout(()=>{suppressClick=false},0)}};
    el.addEventListener('pointerup',finish);el.addEventListener('pointercancel',finish);
    el.addEventListener('click',event=>{
      event.stopPropagation();if(suppressClick){suppressClick=false;return}
      svg.querySelectorAll('.node.selected').forEach(node=>node.classList.remove('selected'));el.classList.add('selected');
      const node=nodes.get(el.dataset.node);if(!node)return;
      if(event.target.closest('.drill-icon')&&node.drilldown&&payload.views[node.drilldown]){history.push(currentId);detailPanel.hidden=true;mount(node.drilldown);return}
      showModuleDetails(node);
    });
  }
}
function showModuleDetails(node){
  const details=node.details||{},panel=detailPanel;panel.replaceChildren();
  const close=document.createElement('button');close.type='button';close.textContent='关闭';close.style.cssText='float:right;padding:4px 9px';close.addEventListener('click',()=>panel.hidden=true);panel.appendChild(close);
  const title=document.createElement('h2');title.textContent=node.title||'';panel.appendChild(title);
  const summary=document.createElement('p');summary.className='detail-summary';summary.textContent=details.summary||node.desc||'待补充';panel.appendChild(summary);
  const fields=[['职责',details.responsibilities],['输入',details.inputs],['输出',details.outputs],['依赖模块',details.depends_on],['调用方',details.used_by],['关键文件',details.key_files],['技术组件',details.tech]];
  for(const [label,values] of fields){const section=document.createElement('section');section.className='detail-section';const heading=document.createElement('h3');heading.textContent=label;section.appendChild(heading);const items=Array.isArray(values)?values:[];if(items.length){const list=document.createElement('ul');for(const value of items){const item=document.createElement('li');item.textContent=String(value);list.appendChild(item)}section.appendChild(list)}else{const empty=document.createElement('div');empty.className='detail-empty';empty.textContent='未提供';section.appendChild(empty)}panel.appendChild(section)}
  const confidence=details.confidence||{},confidenceRows=[['证据',confidence.evidence],['推断',confidence.inference],['待确认',confidence.pending]].filter(([,values])=>Array.isArray(values)&&values.length);
  if(confidenceRows.length){const section=document.createElement('section');section.className='detail-section';const heading=document.createElement('h3');heading.textContent='依据与置信度';section.appendChild(heading);
    for(const [label,values] of confidenceRows){const row=document.createElement('div');row.className='detail-empty';row.textContent=`${label}：${values.join('；')}`;section.appendChild(row)}panel.appendChild(section)}
  if(node.drilldown&&payload.views[node.drilldown]){const actions=document.createElement('div');actions.className='detail-actions';const open=document.createElement('button');open.type='button';open.textContent='查看细节链路';open.addEventListener('click',()=>{history.push(currentId);panel.hidden=true;mount(node.drilldown)});actions.appendChild(open);panel.appendChild(actions)}
  panel.hidden=false;
}
function mount(id){
  currentId=id;const view=payload.views[id];if(!view)return;graph=view.graph;if(graph.type==='architecture'&&graph.edges.some(edge=>!edge.layerFlow))throw new Error('架构主图发现模块级连线，拒绝使用交互路由渲染');hardcodedPorts=Boolean(graph.hardcodedPorts);canvas.innerHTML=view.svg;svg=canvas.querySelector('svg');
  if(workspace){workspace.scrollTop=0;workspace.scrollLeft=0}svg.style.transform='';
  const hashLabel=document.getElementById('layout-hash');if(hashLabel)hashLabel.textContent=String(view.layoutHash||'').slice(0,6);
  nodes=new Map(graph.nodes.map(node=>[node.id,node]));layers=new Map(graph.layers.map(layer=>[layer.id,layer]));nodeEls=[...svg.querySelectorAll('.node')];initial=new Map(nodeEls.map(el=>[el.dataset.node,readPosition(el)]));
  storageKey=`architecture-diagram-layout:${payload.root}:${currentId}:${view.layoutHash}`;
  let stale=false;
  try{
    const oldKey=`architecture-diagram-layout:v2:${payload.root}:${currentId}`;
    if(localStorage.getItem(oldKey)!==null){localStorage.removeItem(oldKey);stale=true}
    const prefix=`architecture-diagram-layout:${payload.root}:${currentId}:`;
    const oldKeys=Array.from({length:localStorage.length},(_,index)=>localStorage.key(index)).filter(key=>key&&key.startsWith(prefix)&&key!==storageKey);
    for(const key of oldKeys){localStorage.removeItem(key);stale=true}
    const raw=localStorage.getItem(storageKey),saved=raw?JSON.parse(raw):null;
    if(saved){
      if(saved.layoutHash!==view.layoutHash||!saved.positions||typeof saved.positions!=='object'){localStorage.removeItem(storageKey);stale=true}
      else{
        for(const el of nodeEls){const base=initial.get(el.dataset.node),offset=saved.positions[el.dataset.node];if(base&&offset&&Number.isFinite(Number(offset.dx))&&Number.isFinite(Number(offset.dy)))setPosition(el,{x:base.x+Number(offset.dx),y:base.y+Number(offset.dy)})}
        updateEdges();const failure=auditSavedLayout();
        if(failure){for(const el of nodeEls)setPosition(el,initial.get(el.dataset.node));updateEdges();localStorage.removeItem(storageKey);stale=true}
      }
    }
  }catch(_){stale=true}
  backButton.hidden=history.length===0;attachNodes();try{updateEdges()}catch(error){console.error('连线布局失败',error)}
  if(stale)showNotice('布局已更新，已恢复自动布局');
}
backButton.addEventListener('click',()=>{if(!history.length)return;mount(history.pop())});
function serializedSvg(){const clone=svg.cloneNode(true);clone.querySelectorAll('.node').forEach(node=>node.classList.remove('selected','dragging'));if(graph.type==='architecture'&&currentId===payload.root)clone.querySelectorAll('.drill-icon').forEach(icon=>icon.remove());return '<?xml version="1.0" encoding="UTF-8"?>\n'+new XMLSerializer().serializeToString(clone)}
function download(name,blob){const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
document.getElementById('exportSvg').addEventListener('click',()=>download('架构图.svg',new Blob([serializedSvg()],{type:'image/svg+xml;charset=utf-8'})));
document.getElementById('exportPng').addEventListener('click',()=>{
  const source=new Blob([serializedSvg()],{type:'image/svg+xml;charset=utf-8'}),url=URL.createObjectURL(source),image=new Image();
  image.onload=()=>{const scale=3,canvas=document.createElement('canvas');canvas.width=Number(svg.getAttribute('width'))*scale;canvas.height=Number(svg.getAttribute('height'))*scale;
    const context=canvas.getContext('2d');context.scale(scale,scale);context.drawImage(image,0,0);canvas.toBlob(blob=>{if(blob)download('架构图.png',blob);URL.revokeObjectURL(url)},'image/png')};
  image.onerror=()=>{URL.revokeObjectURL(url);alert('图片导出失败，请重试')};image.src=url;
});
document.getElementById('reset').addEventListener('click',()=>{
  try{localStorage.removeItem(storageKey)}catch(_){}for(const el of nodeEls)setPosition(el,initial.get(el.dataset.node));
  svg.querySelectorAll('.node.selected').forEach(node=>node.classList.remove('selected'));updateEdges();
});
mount(currentId);
"""


_HTML_SCRIPT = r"""
function clientArrowShaftPoints(points,main=false){const result=points.map(point=>({...point}));if(result.length<2)throw new Error('An arrow needs at least two route points');const length=main?18:12,tip=result.at(-1),previous=result.at(-2),dx=tip.x-previous.x,dy=tip.y-previous.y,segmentLength=Math.hypot(dx,dy);if(segmentLength+1e-6<length)throw new Error(`Arrow terminal segment ${segmentLength.toFixed(1)}px is shorter than ${length}px`);result[result.length-1]={x:tip.x-dx/segmentLength*length,y:tip.y-dy/segmentLength*length};return result}
function setClientArrowPath(group,points){const marked=group.dataset.showMarker!=='false',main=group.dataset.layerFlow==='true',shaft=marked?clientArrowShaftPoints(points,main):points,line=group.querySelector('.edge-line');line.setAttribute('d','M '+shaft.map(point=>`${point.x} ${point.y}`).join(' L '));if(marked){const tip=points.at(-1),base=shaft.at(-1);for(const element of [group,line]){element.dataset.arrowTipX=String(tip.x);element.dataset.arrowTipY=String(tip.y);element.dataset.arrowShaftX=String(base.x);element.dataset.arrowShaftY=String(base.y)}}}

const payload=JSON.parse(document.getElementById('payload').textContent);let currentId=payload.root,selectedId=null,edit=false,drag=null,zoom=1;
const original=JSON.parse(JSON.stringify(payload.views));let state=JSON.parse(JSON.stringify(payload.views)),viewStack=[],selectedEdge=null;
const canvas=document.getElementById('canvas'),details=document.getElementById('details'),crumb=document.getElementById('crumb');
try{const saved=localStorage.getItem(`architecture-diagram:${payload.root}`);if(saved){const restored=JSON.parse(saved);if(restored[payload.root]){state=restored;for(const view of Object.values(state))view.svg=clientSvg({...view.diagram,hardcodedPorts:view.hardcodedPorts})}}}catch(_){}
function current(){return state[currentId].diagram}function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function labelImplementationStatus(s){return ({implemented:'已实现',partial:'部分实现',config_only:'仅配置',unknown:'待确认'})[s]||'待确认'}
function show(){canvas.innerHTML=state[currentId].svg||clientSvg(current());crumb.hidden=viewStack.length===0;crumb.textContent=viewStack.length?`返回：${viewStack.map(id=>state[id]?.diagram.title||'主图').join(' / ')}`:'';crumb.onclick=()=>{if(viewStack.length){currentId=viewStack.pop();show()}};details.classList.remove('show');selectedId=null;selectedEdge=null;document.getElementById('openChild').hidden=true;attach();}
function getNode(id){return current().nodes.find(n=>n.id===id)}
function updateEdges(){const svg=canvas.querySelector('#canvas svg')||canvas.querySelector('svg');if(!svg)return;const box={};for(const g of svg.querySelectorAll('.node')){const node=getNode(g.dataset.node),card=g.querySelector('.node-card');if(!node||!card)continue;const matrix=g.transform.baseVal.consolidate()?.matrix;const p=node.position||{};box[node.id]={x:Number(p.x??matrix?.e??0),y:Number(p.y??matrix?.f??0),w:Number(card.getAttribute('width')),h:Number(card.getAttribute('height')),layer:node.layer,cross:current().layers.find(l=>l.id===node.layer)?.crossCutting||false};}const out={},inc={},groups={};for(const edge of current().edges){out[edge.from]=(out[edge.from]||0)+1;inc[edge.to]=(inc[edge.to]||0)+1;(groups[edge.to]||(groups[edge.to]=[])).push(edge)}const ports={};for(const [targetId,members] of Object.entries(groups)){if(members.length<2||!box[targetId])continue;members.sort((a,b)=>(box[a.from].y+box[a.from].h/2)-(box[b.from].y+box[b.from].h/2));members.forEach((edge,i)=>ports[edge.id]=box[targetId].y+box[targetId].h*(i+1)/(members.length+1))}for(const edge of current().edges){const group=svg.querySelector(`[data-edge="${CSS.escape(edge.id)}"]`),a=box[edge.from],b=box[edge.to];if(!group||!a||!b)continue;let points=[];if(current().type==='sequence'){const y=166+(Number(edge.order)||0)*72;points=[{x:a.x+a.w/2,y},{x:b.x+b.w/2,y}]}else if(current().type==='flow'&&current().direction==='LR'){const sy=a.y+a.h/2,ty=inc[edge.to]>1?ports[edge.id]:b.y+b.h/2,forward=a.x+a.w<=b.x,turn=forward?b.x:b.x+b.w,start={x:forward?a.x+a.w:a.x,y:sy};points=Math.abs(sy-ty)<2?[start,{x:turn,y:ty}]:[start,{x:turn,y:sy},{x:turn,y:ty}]}else if(current().type==='flow'&&current().direction==='TB'){const sx=a.x+a.w/2,tx=b.x+b.w/2,sy=a.y+a.h,ty=b.y;points=Math.abs(sx-tx)<2?[{x:sx,y:sy},{x:tx,y:ty}]:[{x:sx,y:sy},{x:tx,y:sy},{x:tx,y:ty}]}else if(edge.kind==='governance'&&(a.cross||b.cross)){const normal=a.cross?b:a,cross=a.cross?a:b,lane=svg.querySelector(`[data-layer="${CSS.escape(normal.layer)}"] rect`),side=svg.querySelector(`[data-layer="${CSS.escape(cross.layer)}"] rect`);if(lane&&side){const y=Number(lane.getAttribute('y'))+Number(lane.getAttribute('height'))/2;points=[{x:Number(lane.getAttribute('x'))+Number(lane.getAttribute('width')),y},{x:Number(side.getAttribute('x')),y}]}}else if(a.layer===b.layer){const right=b.x>a.x;points=[{x:right?a.x+a.w:a.x,y:a.y+a.h/2},{x:right?b.x:b.x+b.w,y:b.y+b.h/2}]}else if(Math.abs(a.x+a.w/2-(b.x+b.w/2))<2){points=[{x:a.x+a.w/2,y:a.y+a.h},{x:b.x+b.w/2,y:b.y}]}else{const sx=a.x+a.w/2,ty=b.y+b.h/2;points=[{x:sx,y:a.y+a.h},{x:sx,y:ty},{x:sx>=b.x+b.w/2?b.x+b.w:b.x,y:ty}]}if(!points.length)continue;setClientArrowPath(group,points);const label=group.querySelector('.edge-label');if(label){let x,y;if(current().type==='flow'&&current().direction==='LR'&&out[edge.from]>1){x=b.x-60;y=b.y+b.h/2-2}else if(current().type==='flow'&&current().direction==='LR'&&inc[edge.to]>1){x=a.x+a.w+60;y=a.y+a.h/2-2}else{const pair=points.slice(1).reduce((best,p,i)=>{const q=points[i],len=Math.abs(p.x-q.x)+Math.abs(p.y-q.y);return len>best.len?{a:q,b:p,len}:best},{len:-1});x=(pair.a.x+pair.b.x)/2;y=(pair.a.y+pair.b.y)/2-(pair.a.y===pair.b.y?10:2)}const w=Math.max(52,[...edge.label].length*15+18),rect=label.querySelector('rect'),text=label.querySelector('text');rect.setAttribute('x',x-w/2);rect.setAttribute('y',y-13);text.setAttribute('x',x);text.setAttribute('y',y+3)}}}
const updateEdgesBase=updateEdges;updateEdges=function(){updateEdgesBase();if(current().type!=='flow'||current().direction!=='LR')return;const svg=canvas.querySelector('svg');if(!svg)return;const groups={};for(const edge of current().edges)(groups[edge.to]||(groups[edge.to]=[])).push(edge);for(const members of Object.values(groups)){if(members.length<2)continue;for(const edge of members){const from=svg.querySelector(`[data-node="${CSS.escape(edge.from)}"]`),to=svg.querySelector(`[data-node="${CSS.escape(edge.to)}"]`),path=svg.querySelector(`[data-edge="${CSS.escape(edge.id)}"] .edge-line`),label=svg.querySelector(`[data-edge="${CSS.escape(edge.id)}"] .edge-label`);if(!from||!to||!path)continue;const matrixFrom=from.transform.baseVal.consolidate()?.matrix,matrixTo=to.transform.baseVal.consolidate()?.matrix,a={x:Number(from.dataset.x??matrixFrom?.e??0),y:Number(from.dataset.y??matrixFrom?.f??0),w:Number(from.querySelector('.node-card').getAttribute('width')),h:Number(from.querySelector('.node-card').getAttribute('height'))},b={x:Number(to.dataset.x??matrixTo?.e??0),y:Number(to.dataset.y??matrixTo?.f??0),w:Number(to.querySelector('.node-card').getAttribute('width'))},forward=a.x+a.w<=b.x,sy=a.y+a.h/2,startX=forward?a.x+a.w:a.x,endX=forward?b.x:b.x+b.w;path.setAttribute('d',`M ${startX} ${sy} L ${endX} ${sy}`);if(label){const width=Math.max(52,[...edge.label].length*15+18),half=width/2+10,x=forward?a.x+a.w+half:a.x-half,y=sy-2,rect=label.querySelector('rect'),text=label.querySelector('text');rect.setAttribute('x',x-width/2);rect.setAttribute('y',y-13);text.setAttribute('x',x);text.setAttribute('y',y+3)}}}};
const updateEdgesAfterFlow=updateEdges;updateEdges=function(){
 updateEdgesAfterFlow();if(current().type!=='architecture')return;
 const svg=canvas.querySelector('svg');if(!svg)return;
 for(const edge of current().edges){
  if(edge.kind==='governance')continue;
  const source=svg.querySelector(`[data-node="${CSS.escape(edge.from)}"]`),target=svg.querySelector(`[data-node="${CSS.escape(edge.to)}"]`),group=svg.querySelector(`[data-edge="${CSS.escape(edge.id)}"]`);
  if(!source||!target||!group)continue;
  const read=node=>{const matrix=node.transform.baseVal.consolidate()?.matrix;return {x:Number(node.dataset.x??matrix?.e??0),y:Number(node.dataset.y??matrix?.f??0),w:Number(node.querySelector('.node-card').getAttribute('width')),h:Number(node.querySelector('.node-card').getAttribute('height')),layer:node.dataset.layer}};
  const a=read(source),b=read(target),sx=a.x+a.w/2,tx=b.x+b.w/2,sy=a.y+a.h/2,ty=b.y+b.h/2;let points;
  if(a.layer===b.layer){const right=tx>sx,start={x:right?a.x+a.w:a.x,y:sy},end={x:right?b.x:b.x+b.w,y:ty};points=Math.abs(sy-ty)<2?[start,end]:[start,{x:end.x,y:sy},end]}
  else if(ty>=sy){const start={x:sx,y:a.y+a.h},end={x:tx,y:b.y};points=Math.abs(sx-tx)<2?[start,end]:[start,{x:tx,y:start.y},end]}
  else{const start={x:sx,y:a.y},end={x:tx,y:b.y+b.h};points=Math.abs(sx-tx)<2?[start,end]:[start,{x:tx,y:start.y},end]}
  setClientArrowPath(group,points);
  const label=group.querySelector('.edge-label');if(!label)continue;let x,y;
  if(a.layer===b.layer){x=(points[0].x+points.at(-1).x)/2;y=a.y-13}
  else{const vertical=points.slice(1).map((p,i)=>[points[i],p]).find(([p,q])=>p.x===q.x);if(vertical){const [p,q]=vertical,w=Math.max(52,[...edge.label].length*11+16);x=p.x+(b.x>=a.x?w/2+8:-w/2-8);y=(p.y+q.y)/2}else{x=(points[0].x+points.at(-1).x)/2;y=(points[0].y+points.at(-1).y)/2-12}}
  const width=Math.max(52,[...edge.label].length*11+16),rect=label.querySelector('rect'),text=label.querySelector('text');rect.setAttribute('x',x-width/2);rect.setAttribute('y',y-13);text.setAttribute('x',x);text.setAttribute('y',y+3);
 }
};
function wrapClient(text,max=20){const out=[];let line='';for(const ch of [...String(text||'')]){if(line.length>=max){out.push(line);line=ch}else line+=ch}if(line)out.push(line);return out}
function fitClient(text,max){const chars=[...String(text||'')];return chars.length<=max?chars.join(''):chars.slice(0,Math.max(0,max-1)).join('')+'…'}
function baseNodeSize(n,compact=false,fullDetail=false){if(fullDetail){const title=n.title||'',description=n.desc||'',w=Math.max(200,[...title].length*15+48,Math.ceil([...description].length*12/2)+42),desc=wrapClient(description,Math.floor((w-42)/12));if(desc.length>2)throw new Error('下钻模块说明超过两行：'+n.id);return {title:title?[title]:[],desc,w,h:Math.max(58,22+17+(14*desc.length))}}if(compact){let title=wrapClient(n.title,17);if(title.length>2){title=title.slice(0,2);title[1]=fitClient(title[1],17)}const w=Math.max(210,Math.min(300,Math.max(...title.map(x=>[...x].length*15),0)+44)),desc=fitClient(n.desc||'',Math.floor((w-42)/12));return {title,desc:desc?[desc]:[],w,h:Math.min(68,Math.max(58,31+17*title.length+(desc?14:0)))}}const title=wrapClient(n.title,11),desc=wrapClient(n.desc||'',17);return {title,desc,w:Math.max(194,Math.min(280,Math.max(...title.map(x=>[...x].length*20),0)+42)),h:Math.max(108,64+28*title.length+21*desc.length)}}
function archLayerStyle(layer,index){if(layer.crossCutting)return {fill:'#FFF7ED',stroke:'#F97316'};const name=layer.name||'';let key=name.includes('接入')||name.includes('入口')?'access':name.includes('编排')||name.includes('路由')||name.includes('调度')?'orchestration':name.includes('能力')||name.includes('工具')?'capability':name.includes('业务服务')||name.includes('业务层')?'business':name.includes('数据')||name.includes('存储')||name.includes('依赖')?'data':['access','orchestration','capability','business','data'][index%5];return ({access:{fill:'#EFF6FF',stroke:'#3B82F6'},orchestration:{fill:'#F0FDF4',stroke:'#22C55E'},capability:{fill:'#F5F3FF',stroke:'#8B5CF6'},business:{fill:'#FFFBEB',stroke:'#F59E0B'},data:{fill:'#ECFEFF',stroke:'#06B6D4'}})[key]}
function clientSvg(graph){const arrowId=(color,main=false)=>`${main?'arrow-main-':'arrow-'}${String(color).replace(/[^0-9a-f]/gi,'').toUpperCase()}`;const markerDef=(color,main=false)=>{const length=main?18:12,height=main?14:10;return `<marker id="${arrowId(color,main)}" viewBox="0 0 ${length} ${height}" markerWidth="${length}" markerHeight="${height}" refX="0" refY="${height/2}" orient="auto" markerUnits="userSpaceOnUse"><path d="M 0 0 L ${length} ${height/2} L 0 ${height} Z" fill="${color}"/></marker>`};const edgeColor=e=>{const data=['db_read','db_write','cache','vector_query'].includes(e.kind);return graph.type==='architecture'?(e.strokeColor|| (e.kind==='governance'?'#F97316':e.layerFlow?'#155EEF':e.main?'#475569':data?'#0891B2':'#64748B')):(e.kind==='governance'?'#D4A24C':e.returnEdge?'#7C3AED':e.async?'#7C3AED':e.main?'#155EEF':data?'#0F766E':'#94A3B8')};const nodeSize=(n,compact=graph.type==='architecture')=>baseNodeSize(n,compact,Boolean(graph.hardcodedPorts));const nodes=graph.nodes||[],edges=graph.edges||[],layers=graph.layers||[],pos={},layerBoxes=[];let width=1000,height=350;
if(graph.type==='architecture'){
 const ordinary=layers.filter(layer=>!layer.crossCutting),cross=layers.filter(layer=>layer.crossCutting);
 const rows=ordinary.map(layer=>{const members=nodes.filter(n=>n.layer===layer.id).sort((a,b)=>(a.order??99999)-(b.order??99999));return {layer,members,h:Math.max(168,...members.map(n=>nodeSize(n,true).h+100))}});
 const columnWidths={};for(const row of rows)row.members.forEach((n,i)=>{const column=Number.isInteger(n.column)?n.column:i;columnWidths[column]=Math.max(columnWidths[column]||0,nodeSize(n,true).w)});
 const columns=Object.keys(columnWidths).map(Number).sort((a,b)=>a-b),columnX={};let cx=36+220;for(const column of columns){columnX[column]=cx;cx+=columnWidths[column]+24}
 const mainW=Math.max(1080,cx-36+48);width=36+mainW+(cross.length?302:0)+36;let y=82;
 for(const row of rows){layerBoxes.push({...row.layer,x:36,y,width:mainW,height:row.h,crossCutting:false});const rowH=Math.max(...row.members.map(n=>nodeSize(n,true).h));const cardY=y+82+Math.max(0,(row.h-82-rowH)/2);row.members.forEach((n,i)=>{const s=nodeSize(n,true),p=n.position||{},column=Number.isInteger(n.column)?n.column:i,x=columnX[column]+(columnWidths[column]-s.w)/2;pos[n.id]={x:p.x??x,y:p.y??cardY,w:s.w,h:rowH,layer:n.layer,compact:true}});y+=row.h+45}
 height=y+62;
 if(cross.length){const sideX=36+mainW+32,sideH=Math.max(240,height-102),layer=cross[0],members=nodes.filter(n=>n.layer===layer.id),cardH=Math.max(58,...members.map(n=>nodeSize(n,true).h)),available=Math.max(0,sideH-92-cardH),slotGap=members.length>1?available/(members.length-1):0;layerBoxes.push({...layer,x:sideX,y:82,width:270,height:sideH,crossCutting:true});members.forEach((n,i)=>{const s=nodeSize(n,true),p=n.position||{};pos[n.id]={x:p.x??sideX+16,y:p.y??82+64+i*slotGap,w:238,h:s.h,layer:n.layer,cross:true,compact:true}})}
}
else if(graph.type==='sequence'){width=Math.max(820,nodes.length*230+90);height=190+edges.length*72+42;nodes.forEach((n,i)=>{const s=nodeSize(n);pos[n.id]={x:45+i*(width-90)/Math.max(1,nodes.length-1)-s.w/2,y:72,w:s.w,h:60,layer:'sequence'}})}
else {
const groups=layers.map(l=>({layer:l,members:nodes.filter(n=>n.layer===l.id).sort((a,b)=>(a.order??99999)-(b.order??99999))})).filter(g=>g.members.length);
if(!groups.length){for(const n of nodes){const key=n.layer||'步骤';let group=groups.find(x=>x.layer.id===key);if(!group){group={layer:{id:key,name:key},members:[]};groups.push(group)}group.members.push(n)}}
const gap=36,maxW=Math.max(194,...nodes.map(n=>nodeSize(n).w)),maxH=Math.max(108,...nodes.map(n=>nodeSize(n).h));
if(graph.direction==='LR'){
const stackHeights=groups.map(g=>g.members.reduce((sum,n)=>sum+nodeSize(n).h,0)+Math.max(0,g.members.length-1)*48),maxStack=Math.max(maxH,...stackHeights),stepX=maxW+180,laneY=64,expandedTargets={};
groups.forEach((g,i)=>{if(g.members.length!==1)return;const target=g.members[0],inbound=edges.filter(e=>e.to===target.id);if(inbound.length<2)return;const sourceIndices=[...new Set(inbound.map(e=>groups.findIndex(group=>group.members.some(n=>n.id===e.from))))];if(sourceIndices.length===1&&sourceIndices[0]>=0&&sourceIndices[0]<i)expandedTargets[target.id]=sourceIndices[0]});
groups.forEach((g,i)=>{const laneH=Math.max(220,maxStack+96);layerBoxes.push({...g.layer,x:28+i*stepX,y:laneY,width:stepX-24,height:laneH,crossCutting:false});let y=laneY+74+(maxStack-stackHeights[i])/2;if(g.members.length===1&&expandedTargets[g.members[0].id]!==undefined){const sourceIndex=expandedTargets[g.members[0].id];y=laneY+74+(maxStack-stackHeights[sourceIndex])/2}for(const n of g.members){const s=nodeSize(n),p=n.position||{},h=expandedTargets[n.id]!==undefined?stackHeights[expandedTargets[n.id]]:s.h;pos[n.id]={x:p.x??48+i*stepX,y:p.y??y,w:s.w,h,layer:g.layer.id};y+=h+48}});
width=Math.max(900,80+groups.length*stepX);height=Math.max(330,laneY+Math.max(220,maxStack+96)+28);
}else{
const widths=groups.map(g=>g.members.reduce((sum,n)=>sum+nodeSize(n).w,0)+Math.max(0,g.members.length-1)*gap),maxRow=Math.max(maxW,...widths),stepY=maxH+126;
groups.forEach((g,i)=>{const laneY=56+i*stepY,laneW=Math.max(900,maxRow+96);layerBoxes.push({...g.layer,x:28,y:laneY,width:laneW,height:maxH+98,crossCutting:false});let x=48+(laneW-96-widths[i])/2;for(const n of g.members){const s=nodeSize(n),p=n.position||{};pos[n.id]={x:p.x??x,y:p.y??laneY+64,w:s.w,h:s.h,layer:g.layer.id};x+=s.w+gap}});
 width=Math.max(900,56+Math.max(900,maxRow+96));height=Math.max(330,56+groups.length*stepY)+42;
}}
 const palette=['#DBEAFE','#DCFCE7','#F3E8FF','#FEF3C7','#E0F2FE','#FFE4E6'];let body='';
 layerBoxes.forEach((l,i)=>{const style=graph.type==='architecture'?archLayerStyle(l,i):{fill:l.crossCutting?'#FFF9ED':palette[i%palette.length],stroke:l.crossCutting?'#D6A85F':'#C7D6EA'};body+=`<g class="layer${graph.type==='architecture'?' architecture-layer':''}" data-layer="${esc(l.id)}"><rect x="${l.x}" y="${l.y}" width="${l.width}" height="${l.height}" rx="16" fill="${style.fill}" stroke="${style.stroke}" stroke-width="1.4"/><text class="layer-title"${graph.type==='architecture'?` fill="${style.stroke}"`:''} x="${l.x+18}" y="${l.y+27}">${esc(l.name)}</text>${l.desc?`<text class="layer-desc" x="${l.x+18}" y="${l.y+47}">${esc(l.desc)}</text>`:''}</g>`});
if(graph.type==='sequence')for(const n of nodes){const p=pos[n.id];body+=`<path class="lifeline" d="M ${p.x+p.w/2} 135 L ${p.x+p.w/2} ${height-52}"/>`}
 const outDegree={},inDegree={},incomingGroups={};for(const e of edges){outDegree[e.from]=(outDegree[e.from]||0)+1;inDegree[e.to]=(inDegree[e.to]||0)+1;(incomingGroups[e.to]||(incomingGroups[e.to]=[])).push(e)}const targetPort={};for(const [targetId,members] of Object.entries(incomingGroups)){if(members.length<2||!pos[targetId])continue;const target=pos[targetId];members.sort((a,b)=>(pos[a.from].y+pos[a.from].h/2)-(pos[b.from].y+pos[b.from].h/2));members.forEach((e,i)=>{const source=pos[e.from],center=source.y+source.h/2;targetPort[e.id]=graph.type==='flow'&&graph.direction==='LR'?Math.max(target.y+16,Math.min(target.y+target.h-16,center)):target.y+target.h*(i+1)/(members.length+1)})}
 for(const e of edges){const a=pos[e.from],b=pos[e.to];if(!a||!b)continue;let pts=[],gov=e.kind==='governance';if(graph.type==='sequence'){const yy=166+(Number(e.order)||0)*72;pts=[{x:a.x+a.w/2,y:yy},{x:b.x+b.w/2,y:yy}]}else if(graph.type==='flow'&&graph.direction==='LR'){const sy=a.y+a.h/2,ty=inDegree[e.to]>1?targetPort[e.id]:b.y+b.h/2,forward=a.x+a.w<=b.x,xx=forward?b.x:b.x+b.w,start={x:forward?a.x+a.w:a.x,y:sy};pts=Math.abs(sy-ty)<2?[start,{x:xx,y:ty}]:[start,{x:xx,y:sy},{x:xx,y:ty}]}else if(graph.type==='flow'&&graph.direction==='TB'){const sx=a.x+a.w/2,tx=b.x+b.w/2,sy=a.y+a.h,ty=b.y;pts=Math.abs(sx-tx)<2?[{x:sx,y:sy},{x:tx,y:ty}]:[{x:sx,y:sy},{x:tx,y:sy},{x:tx,y:ty}]}else if(graph.type==='architecture'&&a.layer===b.layer){const right=b.x>a.x,sy=a.y+a.h/2;pts=[{x:right?a.x+a.w:a.x,y:sy},{x:right?b.x:b.x+b.w,y:b.y+b.h/2}]}else if(graph.type==='architecture'&&b.y+b.h/2>=a.y+a.h/2){const start={x:a.x+a.w/2,y:a.y+a.h},end={x:b.x+b.w/2,y:b.y};pts=Math.abs(start.x-end.x)<2?[start,end]:[start,{x:end.x,y:start.y},end]}else if(graph.type==='architecture'){const start={x:a.x+a.w/2,y:a.y},end={x:b.x+b.w/2,y:b.y+b.h};pts=Math.abs(start.x-end.x)<2?[start,end]:[start,{x:end.x,y:start.y},end]}else if(a.layer===b.layer){const right=b.x>a.x,sy=a.y+a.h/2;pts=[{x:right?a.x+a.w:a.x,y:sy},{x:right?b.x:b.x+b.w,y:b.y+b.h/2}]}else if(Math.abs(a.x+a.w/2-(b.x+b.w/2))<2){pts=[{x:a.x+a.w/2,y:a.y+a.h},{x:b.x+b.w/2,y:b.y}]}else{const sx=a.x+a.w/2,ty=b.y+b.h/2;pts=[{x:sx,y:a.y+a.h},{x:sx,y:ty},{x:sx>=b.x+b.w/2?b.x+b.w:b.x,y:ty}]}
 const color=edgeColor(e),main=graph.type==='architecture'&&Boolean(e.layerFlow),marked=e.showMarker!==false,shaft=marked?clientArrowShaftPoints(pts,main):pts,d='M '+shaft.map(p=>`${p.x} ${p.y}`).join(' L '),dash=gov?' stroke-dasharray="5 5"':e.async?' stroke-dasharray="7 6"':'';const pair=pts.length>1?pts.reduce((best,p,i)=>i&&Math.abs(p.x-pts[i-1].x)+Math.abs(p.y-pts[i-1].y)>best.len?{a:pts[i-1],b:p,len:Math.abs(p.x-pts[i-1].x)+Math.abs(p.y-pts[i-1].y)}:best,{len:-1}):null;let label='';if(!gov&&!e.layerFlow&&pair){let lx=(pair.a.x+pair.b.x)/2,ly=(pair.a.y+pair.b.y)/2-(pair.a.y===pair.b.y?10:2),lw;if(graph.type==='architecture'){lw=Math.max(52,[...e.label].length*11+16);if(a.layer===b.layer){lx=(pts[0].x+pts[pts.length-1].x)/2;ly=a.y-13}else{const vertical=pts.slice(1).map((p,i)=>[pts[i],p]).find(([p,q])=>p.x===q.x);if(vertical){const [p,q]=vertical;lx=p.x+(b.x>=a.x?lw/2+8:-lw/2-8);ly=(p.y+q.y)/2}}}else{lw=Math.max(52,[...e.label].length*15+18);const half=lw/2+10;if(graph.type==='flow'&&graph.direction==='LR'&&outDegree[e.from]>1){lx=b.x-half;ly=b.y+b.h/2-2}else if(graph.type==='flow'&&graph.direction==='LR'&&inDegree[e.to]>1){lx=a.x+a.w+half;ly=a.y+a.h/2-2}}label=`<g class="edge-label"><rect x="${lx-lw/2}" y="${ly-13}" width="${lw}" height="22" rx="7" fill="#fff" fill-opacity=".94"/><text x="${lx}" y="${ly+3}" text-anchor="middle">${esc(e.label)}</text></g>`}const arrowGeometry=marked?` data-arrow-shaft-x="${shaft.at(-1).x}" data-arrow-shaft-y="${shaft.at(-1).y}" data-arrow-tip-x="${pts.at(-1).x}" data-arrow-tip-y="${pts.at(-1).y}"`:"";body+=`<g class="edge" data-edge="${esc(e.id)}" data-from="${esc(e.from)}" data-to="${esc(e.to)}" data-kind="${esc(e.kind||'other')}" data-layer-flow="${String(Boolean(e.layerFlow))}" data-show-marker="${String(e.showMarker!==false)}"${arrowGeometry}><path class="edge-line"${arrowGeometry} d="${d}" fill="none" stroke="${color}" stroke-width="${graph.type==='architecture'&&e.layerFlow?3.6:1.8}" stroke-linecap="butt"${dash}${e.showMarker===false?'':` marker-end="url(#${arrowId(color,graph.type==='architecture'&&Boolean(e.layerFlow))})"`} vector-effect="non-scaling-stroke"/>${label}</g>`}
 for(const n of nodes){const p=pos[n.id],compact=graph.type==='architecture'||Boolean(graph.hardcodedPorts),s=nodeSize(n,graph.type==='architecture');if(!p)continue;const titleLine=compact?17:23,descLine=compact?15:18,titleFont=compact?15:20,descFont=compact?12:13,titleHeight=s.title.length*titleLine,descHeight=s.desc.length*descLine,start=Math.max(titleFont+2,(p.h-titleHeight-descHeight)/2+titleFont),layer=layers.find(x=>x.id===n.layer),accent=graph.type==='architecture'?archLayerStyle(layer||{},layers.indexOf(layer)).stroke:compact?'#CBD5E1':'#3B82F6',compactClass=compact?' compact':'';const card=compact?`<rect class="node-card" x="0" y="0" width="${p.w}" height="${p.h}" rx="11" fill="#fff" stroke="#CBD5E1" stroke-width="1.3" filter="url(#card-shadow)"/><rect x="1" y="5" width="4" height="${p.h-10}" rx="2" fill="${accent}"/>`:`<rect class="node-card" x="0" y="0" width="${p.w}" height="${p.h}" rx="14" fill="#fff" stroke="#B7C7DB" stroke-width="1.5"/>`;const badgeY=compact?6:p.h-27;body+=`<g class="node${compactClass}" data-node="${esc(n.id)}" data-layer="${esc(n.layer||'')}" data-title="${esc(n.title)}" data-desc="${esc(n.desc||'')}" data-x="${p.x}" data-y="${p.y}" transform="translate(${p.x} ${p.y})" tabindex="0" role="button">${card}${s.title.map((line,i)=>`<text class="node-title" x="${p.w/2}" y="${start+i*titleLine}" text-anchor="middle">${esc(line)}</text>`).join('')}${s.desc.map((line,i)=>`<text class="node-desc" x="${p.w/2}" y="${start+titleHeight+3+i*descLine}" text-anchor="middle">${esc(line)}</text>`).join('')}${n.drilldown?`<g class="drill-icon" role="button" tabindex="0" aria-label="进入下钻图"><circle cx="${p.w-16}" cy="16" r="8" fill="#F1F5F9" stroke="#CBD5E1"/><path d="M ${p.w-19} 19 L ${p.w-13} 13 M ${p.w-18} 13 H ${p.w-13} V 18" fill="none" stroke="#475569" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></g>`:''}</g>`}
 const legendItems=new Map(),addLegend=(key,label,color,dash='',marker=true,shape='line',mainMarker=false)=>{if(!legendItems.has(key))legendItems.set(key,{key,label,color,dash,marker,shape,mainMarker})};
 if(graph.type==='architecture'){const used=new Set();layers.forEach((l,i)=>{const style=archLayerStyle(l,i),key=style.fill+'|'+style.stroke+'|'+l.name;if(used.has(key))return;used.add(key);addLegend('layer-'+i,l.name,style.stroke,'',false,'swatch')})}
 for(const e of edges){const data=['db_read','db_write','cache','vector_query'].includes(e.kind),gov=e.kind==='governance',color=edgeColor(e);if(gov)addLegend('governance','治理约束',color,'5 5',true);else if(e.async)addLegend('async','异步调用',color,'7 6');else if(e.main||e.layerFlow)addLegend('main',graph.type==='architecture'?'层间连接':'主链路',color,'',true,'line',graph.type==='architecture'&&Boolean(e.layerFlow));else if(data)addLegend('data','数据访问',color);else addLegend('secondary','一般调用',color)}
 if(graph.type==='sequence')addLegend('lifeline','参与者生命线','#94A3B8','5 6',false);
 if(legendItems.size){let lx=36;const ly=height-20;body+='<g class="diagram-legend" aria-label="连线图例">';for(const item of legendItems.values()){if(item.shape==='swatch')body+=`<rect data-legend-key="${item.key}" x="${lx}" y="${ly-9}" width="10" height="10" rx="2" fill="${item.color}" stroke="${item.color}"/>`;else{const markerMain=Boolean(item.mainMarker),length=markerMain?18:12,marked=Boolean(item.marker),shaftEnd=lx+24-(marked?length:0),geometry=marked?` data-arrow-shaft-x="${shaftEnd}" data-arrow-shaft-y="${ly-4}" data-arrow-tip-x="${lx+24}" data-arrow-tip-y="${ly-4}"`:"";body+=`<path data-legend-key="${item.key}"${geometry} d="M ${lx} ${ly-4} L ${shaftEnd} ${ly-4}" fill="none" stroke="${item.color}" stroke-width="${markerMain?3.6:1.8}" stroke-linecap="butt"${markerMain?' data-marker-size=\"main\"':''}${item.dash?` stroke-dasharray="${item.dash}"`:''}${marked?` marker-end="url(#${arrowId(item.color,markerMain)})"`:''}/>`};const textX=lx+(item.shape==='swatch'?14:30);body+=`<text x="${textX}" y="${ly}" font-size="12" fill="#475569">${esc(item.label)}</text>`;lx=textX+[...item.label].length*12+15}body+='</g>'}
 const markerPairs=new Map();for(const e of edges){if(e.showMarker===false)continue;const color=edgeColor(e),main=graph.type==='architecture'&&Boolean(e.layerFlow);markerPairs.set(arrowId(color,main),[color,main])}if(graph.type==='architecture')markerPairs.set(arrowId('#155EEF',true),['#155EEF',true]);const markerDefs=[...markerPairs.values()].map(([color,main])=>markerDef(color,main)).join('');
 return `<svg class="${graph.type==='architecture'?'architecture-diagram':graph.hardcodedPorts?'architecture-detail':''}" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" role="img" aria-label="${esc(graph.title)}"><defs><filter id="card-shadow" x="-10%" y="-10%" width="120%" height="130%"><feDropShadow dx="0" dy="1" stdDeviation="1.3" flood-color="#0f172a" flood-opacity=".09"/></filter>${markerDefs}</defs><rect width="100%" height="100%" fill="#F8FAFC"/><text class="diagram-title" x="36" y="38">${esc(graph.title)}</text>${body}</svg>`}
function rebuild(){state[currentId].svg=clientSvg({...current(),hardcodedPorts});show();persist()}
function registerChildren(graph){for(const child of graph.subDiagrams||[]){if(!state[child.id])state[child.id]={diagram:child,svg:clientSvg(child)};registerChildren(child)}}
function persist(){try{localStorage.setItem(`architecture-diagram:${payload.root}`,JSON.stringify(state))}catch(_){}}
function showDetails(node){document.getElementById('detailTitle').textContent=node.title;document.getElementById('detailDesc').textContent=node.desc||'未填写';document.getElementById('detailStatus').textContent=labelImplementationStatus(node.status);for(const [id,items] of [['detailInputs',node.inputs],['detailOutputs',node.outputs],['detailEvidence',node.evidence?.map(x=>`${x.path}${x.line?`:${x.line}`:''}${x.claim?`：${x.claim}`:''}`)]]){const box=document.getElementById(id);box.replaceChildren();for(const item of items||[]){const row=document.createElement('div');row.textContent=item;box.appendChild(row)}if(!(items||[]).length){const row=document.createElement('div');row.textContent='未提供';box.appendChild(row)}}const sel=document.getElementById('detailLayer');sel.innerHTML='';for(const layer of current().layers){const o=document.createElement('option');o.value=layer.id;o.textContent=layer.name;o.selected=layer.id===node.layer;sel.appendChild(o)}sel.onchange=()=>{node.layer=sel.value;node.position=undefined;rebuild()};details.classList.add('show')}
function attach(){const svg=canvas.querySelector('svg');if(!svg)return;svg.querySelectorAll('.node').forEach(g=>{const n=getNode(g.dataset.node);if(!n)return;g.dataset.x=n.position?.x??g.transform.baseVal.consolidate()?.matrix.e??0;g.dataset.y=n.position?.y??g.transform.baseVal.consolidate()?.matrix.f??0;
g.addEventListener('mouseenter',()=>{const related=new Set(current().edges.filter(e=>e.from===n.id||e.to===n.id).flatMap(e=>[e.from,e.to]));svg.querySelectorAll('.node').forEach(x=>x.classList.toggle('dim',x!==g&&!related.has(x.dataset.node)));svg.querySelectorAll('.edge').forEach(x=>x.classList.toggle('dim',x.dataset.from!==n.id&&x.dataset.to!==n.id));g.classList.add('highlight')});
g.addEventListener('mouseleave',()=>{svg.querySelectorAll('.dim,.highlight').forEach(x=>x.classList.remove('dim','highlight'))});
g.addEventListener('click',e=>{e.stopPropagation();selectedId=n.id;selectedEdge=null;svg.querySelectorAll('.node').forEach(x=>x.classList.toggle('selected',x===g));showDetails(n);if(n.drilldown&&state[n.drilldown]){document.getElementById('openChild').hidden=false;document.getElementById('openChild').onclick=()=>{viewStack.push(currentId);currentId=n.drilldown;show()}}else document.getElementById('openChild').hidden=true});
g.addEventListener('dblclick',e=>{if(!edit)return;e.stopPropagation();const title=prompt('模块名称（中文）',n.title);if(title!==null&&title.trim()){n.title=title.trim();const desc=prompt('模块说明（中文）',n.desc||'');if(desc!==null)n.desc=desc;rebuild();}});
g.addEventListener('pointerdown',e=>{if(!edit||e.button!==0)return;e.stopPropagation();g.setPointerCapture(e.pointerId);g.classList.add('dragging');drag={g,n,startX:e.clientX,startY:e.clientY,x:Number(g.dataset.x),y:Number(g.dataset.y),scale:Number(svg.getBoundingClientRect().width)/Number(svg.viewBox.baseVal.width)};});
g.addEventListener('pointermove',e=>{if(!drag||drag.g!==g)return;const dx=(e.clientX-drag.startX)/Math.max(.1,drag.scale),dy=(e.clientY-drag.startY)/Math.max(.1,drag.scale);const x=drag.x+dx,y=drag.y+dy;g.setAttribute('transform',`translate(${x} ${y})`);g.dataset.x=x;g.dataset.y=y;drag.n.position={...(drag.n.position||{}),x,y};updateEdges()});
g.addEventListener('pointerup',()=>{if(drag?.g===g){g.classList.remove('dragging');drag=null;persist()}});});
svg.querySelectorAll('.edge').forEach(g=>g.addEventListener('click',e=>{e.stopPropagation();selectedEdge=g.dataset.edge;selectedId=null;svg.querySelectorAll('.node').forEach(x=>x.classList.remove('selected'));g.classList.add('selected')}));
svg.addEventListener('dblclick',e=>{if(edit&&e.target===svg){const n=getNode(selectedId);if(n){const desc=prompt('模块说明（中文）',n.desc||'');if(desc!==null){n.desc=desc;show()}}}});
}
document.getElementById('edit').onclick=e=>{edit=!edit;e.currentTarget.classList.toggle('active',edit);e.currentTarget.textContent=edit?'完成编辑':'编辑模式'};
document.getElementById('relayout').onclick=()=>{for(const node of current().nodes)delete node.position;rebuild()};
document.getElementById('closeDetails').onclick=()=>details.classList.remove('show');
document.getElementById('deleteNode').onclick=()=>{const graph=current();if(selectedId){graph.nodes=graph.nodes.filter(n=>n.id!==selectedId);graph.edges=graph.edges.filter(e=>e.from!==selectedId&&e.to!==selectedId);selectedId=null;rebuild()}else if(selectedEdge){graph.edges=graph.edges.filter(e=>e.id!==selectedEdge);selectedEdge=null;rebuild()}};
document.getElementById('addNode').onclick=()=>{const graph=current();const title=prompt('新模块名称（中文）');if(!title)return;let layer='';if(graph.layers.length){const choices=graph.layers.map((x,i)=>`${i+1}. ${x.name}`).join('\n');const choice=Number(prompt(`选择所属层：\n${choices}`))-1;if(!graph.layers[choice])return;layer=graph.layers[choice].id}const desc=prompt('模块说明（中文）','')||'';graph.nodes.push({id:`new-node-${Date.now()}`,...(layer?{layer}:{}),title,desc,status:'partial'});for(const n of graph.nodes)delete n.position;rebuild()};
document.getElementById('addEdge').onclick=()=>{const graph=current();if(graph.nodes.length<2){alert('至少需要两个模块');return}const choices=graph.nodes.map((n,i)=>`${i+1}. ${n.title}`).join('\n');const from=Number(prompt('选择起点序号：\n'+choices))-1;const to=Number(prompt('选择终点序号：\n'+choices))-1;if(!graph.nodes[from]||!graph.nodes[to])return;const label=prompt('连线含义（中文）');if(!label)return;graph.edges.push({id:`new-edge-${Date.now()}`,from:graph.nodes[from].id,to:graph.nodes[to].id,label,kind:'call',main:false});rebuild()};
document.getElementById('setDrilldown').onclick=()=>{const node=getNode(selectedId);if(!node){alert('请先选择一个模块');return}const children=(current().subDiagrams||[]).map(x=>`${x.id}：${x.title}`).join('\n');const value=prompt(`输入子图编号或粘贴子图 JSON；输入 0 移除当前下钻。\n可选子图：\n${children}`,node.drilldown||'');if(value===null)return;if(value.trim()==='0'||value.trim()===''){delete node.drilldown;rebuild();return}let childId=value.trim();if(childId.startsWith('{')){let child;try{child=JSON.parse(childId)}catch(error){alert(`子图 JSON 无效：${error.message}`);return}if(!child.id||!Array.isArray(child.nodes)||!Array.isArray(child.edges)||child.id===currentId){alert('子图至少需要唯一编号、模块和连线，且不能指向当前图');return}current().subDiagrams=current().subDiagrams||[];const index=current().subDiagrams.findIndex(x=>x.id===child.id);if(index>=0)current().subDiagrams[index]=child;else current().subDiagrams.push(child);state[child.id]={diagram:child,svg:clientSvg(child)};registerChildren(child);childId=child.id}else if(!state[childId]){alert('没有找到该子图；请从当前子图列表选择，或粘贴子图 JSON');return}node.drilldown=childId;rebuild()};
function download(name,data,type){const a=document.createElement('a');a.href=`data:${type};charset=utf-8,${encodeURIComponent(data)}`;a.download=name;a.click()}
document.getElementById('exportJson').onclick=()=>download('architecture-diagram.json',JSON.stringify(current(),null,2),'application/json');
document.getElementById('exportSvg').onclick=()=>download('架构图.svg',canvas.querySelector('svg').outerHTML,'image/svg+xml');
document.getElementById('exportPng').onclick=()=>{const svg=canvas.querySelector('svg'),blob=new Blob([svg.outerHTML],{type:'image/svg+xml'}),url=URL.createObjectURL(blob),img=new Image();img.onload=()=>{const c=document.createElement('canvas');c.width=img.width*2;c.height=img.height*2;c.getContext('2d').drawImage(img,0,0,c.width,c.height);c.toBlob(b=>{const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='架构图.png';a.click();URL.revokeObjectURL(url)},'image/png')};img.src=url};
document.getElementById('importJson').onchange=async e=>{try{const data=JSON.parse(await e.target.files[0].text());if(!data.id||!Array.isArray(data.nodes)||!Array.isArray(data.edges))throw Error('结构数据不正确');registerChildren(data);state[data.id]={diagram:data,svg:clientSvg(data)};currentId=data.id;viewStack=[];show();persist();alert('已导入结构数据，可继续编辑。')}catch(err){alert(`导入失败：${err.message}`)}e.target.value=''};
document.getElementById('reset').onclick=()=>{state=JSON.parse(JSON.stringify(original));currentId=payload.root;viewStack=[];try{localStorage.removeItem(`architecture-diagram:${payload.root}`)}catch(_){}show()};
document.getElementById('zoomIn').onclick=()=>{zoom=Math.min(2.5,zoom*1.15);canvas.querySelector('svg').style.transform=`scale(${zoom})`;canvas.querySelector('svg').style.transformOrigin='top center'};document.getElementById('zoomOut').onclick=()=>{zoom=Math.max(.45,zoom/1.15);canvas.querySelector('svg').style.transform=`scale(${zoom})`;canvas.querySelector('svg').style.transformOrigin='top center'};document.getElementById('fit').onclick=()=>{zoom=1;const s=canvas.querySelector('svg');s.style.transform='';document.querySelector('.workspace').scrollTo({top:0,left:0,behavior:'smooth'})};
show();
"""


_ARCHITECTURE_HTML_STYLE = r"""
*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;font-family:"Microsoft YaHei","Noto Sans CJK SC",sans-serif;color:#0f172a;background:#F8FAFC}
body{display:flex;flex-direction:column;overflow:hidden}.toolbar{display:flex;flex:0 0 52px;gap:8px;align-items:center;justify-content:flex-end;padding:7px 14px;background:#fff;border-bottom:1px solid #e2e8f0;box-shadow:0 1px 3px #0f172a0d;z-index:1}
button{font:inherit;font-size:13px;border:1px solid #cbd5e1;background:#fff;color:#334155;border-radius:8px;padding:7px 12px;cursor:pointer}button:hover{background:#f1f5f9}#back:not([hidden]){margin-right:auto;color:#1d4ed8;border-color:#bfdbfe;background:#eff6ff}
#module-details[hidden]{display:none}#module-details{position:fixed;right:20px;bottom:20px;z-index:3;width:min(390px,calc(100vw - 32px));max-height:72vh;overflow:auto;background:#fff;border:1px solid #cbd5e1;border-radius:12px;padding:16px;box-shadow:0 10px 32px #0f172a22}#module-details h2{font-size:17px;margin:0 0 10px}#module-details .detail-summary{font-size:13px;line-height:1.6;color:#475569;margin:0 0 12px}.detail-section{border-top:1px solid #e2e8f0;padding-top:9px;margin-top:9px}.detail-section h3{font-size:12px;margin:0 0 5px;color:#64748b}.detail-section ul{padding-left:18px;margin:0;color:#334155;font-size:12px;line-height:1.6;overflow-wrap:anywhere}.detail-empty{color:#94a3b8;font-size:12px;line-height:1.6;overflow-wrap:anywhere}.detail-actions{display:flex;justify-content:flex-end;margin-top:12px}
.workspace{position:relative;overflow-x:hidden;overflow-y:auto;flex:1;min-width:0;width:100%;padding:16px;overscroll-behavior:contain}#canvas{width:100%;min-width:0;min-height:100%;display:flex;justify-content:center;align-items:flex-start}
#canvas svg{display:block;width:100%;max-width:1600px;height:auto;flex:0 1 auto;box-shadow:0 6px 28px #0f172a12;border-radius:12px;background:#F8FAFC;transform:none!important}
#layout-meta{margin-left:8px;padding:3px 7px;border:1px solid #e2e8f0;border-radius:6px;background:#f8fafc;color:#64748b;font-size:10px;line-height:1.3;white-space:nowrap;pointer-events:none}#layout-hash{font-variant-numeric:tabular-nums;letter-spacing:.04em}
#layout-notice[hidden]{display:none}#layout-notice{position:fixed;right:16px;bottom:12px;z-index:5;max-width:min(420px,calc(100vw - 32px));padding:9px 13px;border:1px solid #bfdbfe;border-radius:9px;background:#eff6ff;color:#1e3a8a;font-size:13px;box-shadow:0 4px 14px #0f172a1a}
.node{cursor:grab;touch-action:none;user-select:none;outline:none}.node.dragging{cursor:grabbing}.node.selected .node-card{stroke:#2563EB;stroke-width:2.4;filter:drop-shadow(0 2px 5px #2563eb22)}.drill{font-weight:600}.toolbar button[hidden]{display:none}
.architecture-detail .compact .node-title{font-size:15px}.architecture-detail .compact .node-desc{font-size:12px}.architecture-detail .compact .drill{font-size:10px}
 .architecture-diagram .compact:has(.drill-icon) .node-title,.architecture-detail .compact:has(.drill-icon) .node-title{transform:translateX(-16px)}
@media(max-width:700px){.toolbar{gap:5px;padding:7px 8px}button{padding:6px 8px;font-size:12px}.workspace{padding:8px}}
"""


def render_html(diagram: dict, layout: dict | None = None, *, backend: str = "auto",
                architecture_detail: bool = False,
                precomputed_layouts: dict[str, dict] | None = None) -> str:
    if diagram.get("type") == "architecture" or architecture_detail:
        catalog = _view_catalog(diagram, backend, include_drilldown=True,
                                architecture_detail=architecture_detail, root_layout=layout,
                                precomputed_layouts=precomputed_layouts)
        views = {}
        for view_id, item in catalog.items():
            current = item["diagram"]
            views[view_id] = {
                "svg": item["svg"],
                "layoutHash": item["layoutHash"],
                "graph": {
                    "title": current["title"], "type": current["type"],
                    "direction": current.get("direction", "TB"),
                    "hardcodedPorts": item["hardcodedPorts"],
                    "nodes": [{"id": node["id"], "layer": next((pos.get("layer") for pos in item["layout"]["nodes"] if pos["id"] == node["id"]), node.get("layer", "")),
                               "title": node.get("title", ""), "desc": node.get("desc", ""),
                               "drilldown": node.get("drilldown"), "details": node.get("details", {}),
                               "evidence": node.get("evidence", [])}
                              for node in current.get("nodes", [])],
                    "viewMode": item["layout"].get("viewMode", "graph"),
                    "edgeGroups": [{key: group.get(key) for key in
                                    ("id", "pattern", "edgeIds", "sourceId", "targetId", "forwardEdgeId", "returnEdgeId", "kind")}
                                   for group in item["layout"].get("edgeGroups", [])],
                    "edges": [{key: ("" if key == "label" and edge.get("layerFlow") else edge.get(key)) for key in ("id", "from", "to", "label", "kind", "main", "async", "layerFlow",
                                                               "groupId", "groupPattern", "showMarker", "showLabel", "returnEdge")}
                              for edge in item["layout"].get("edges", [])],
                    "layers": [{key: layer.get(key) for key in ("id", "name", "crossCutting")}
                               for layer in item["layout"].get("layers", [])],
                },
            }
        svg = views[diagram["id"]]["svg"]
        payload = json.dumps({"root": diagram["id"], "views": views}, ensure_ascii=False, separators=(",", ":"))
        payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
        toolbar = ("<header class=\"toolbar\" aria-label=\"架构图工具栏\">"
                   "<button id=\"back\" type=\"button\" aria-label=\"返回上一级\" hidden>返回上一级</button>"
                   "<button id=\"exportSvg\" type=\"button\">导出矢量图</button>"
                   "<button id=\"exportPng\" type=\"button\">导出高清图片</button>"
                   "<button id=\"reset\" type=\"button\">重置布局</button>"
                   "<span id=\"layout-meta\" aria-label=\"布局版本\">布局版本 <span id=\"layout-hash\"></span></span></header>"
                   "<div id=\"layout-notice\" role=\"status\" aria-live=\"polite\" hidden></div>")
        return ("<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
                f"<title>{_esc(diagram['title'])}</title><style>{_ARCHITECTURE_HTML_STYLE}</style></head><body class=\"architecture-only\">{toolbar}"
                f"<main class=\"workspace\"><div id=\"canvas\">{svg}</div></main>"
                "<aside id=\"module-details\" hidden aria-label=\"模块详情\"></aside>"
                f"<script id=\"payload\" type=\"application/json\">{payload}</script><script>{_ARCHITECTURE_HTML_SCRIPT}</script></body></html>")

    views = _view_catalog(diagram, backend)
    payload = json.dumps({"root": diagram["id"], "views": views}, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    toolbar = """<header class="toolbar">
<button id="edit">编辑模式</button><button id="relayout">重新布局</button><button id="addNode">新增模块</button><button id="addEdge">新增连线</button><button id="setDrilldown">设置下钻</button><button id="deleteNode">删除选中</button>
<button id="exportJson">导出结构数据</button><label><button type="button" onclick="document.getElementById('importJson').click()">导入结构数据</button></label><input id="importJson" type="file" accept=".json,application/json" hidden>
<button id="exportSvg">导出矢量图</button><button id="exportPng">导出图片</button><button id="reset">重置</button><button id="openChild" hidden>查看细节</button><button id="crumb" class="crumb" hidden></button><span style="flex:1"></span><button id="zoomOut">−</button><button id="zoomIn">＋</button><button id="fit">适应画布</button>
</header>"""
    return ("<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{_esc(diagram['title'])}</title><style>{_HTML_STYLE}</style></head><body>{toolbar}"
            "<main class=\"workspace\"><div id=\"canvas\"></div></main>"
            "<aside id=\"details\"><button id=\"closeDetails\" style=\"float:right\">关闭</button><div id=\"detailTitle\"></div><div class=\"detail-label\">职责</div><div id=\"detailDesc\"></div><div class=\"detail-label\">输入</div><div id=\"detailInputs\"></div><div class=\"detail-label\">输出</div><div id=\"detailOutputs\"></div><div class=\"detail-label\">实现情况</div><div id=\"detailStatus\"></div><div class=\"detail-label\">所属层</div><select id=\"detailLayer\"></select><div class=\"detail-label\">代码位置</div><div id=\"detailEvidence\"></div></aside>"
            f"<script id=\"payload\" type=\"application/json\">{payload}</script><script>{_HTML_SCRIPT}</script></body></html>")
