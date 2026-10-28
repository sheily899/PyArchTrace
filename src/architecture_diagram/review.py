"""Agent-in-the-loop 视觉闭环协议与可插拔调用接口。"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Callable

from .capture import capture_html, write_capture_report
from .layout import layout_diagram
from .models import require_valid_diagram
from .quality import quality_report
from .render import render_html, render_svg


REVIEW_PROMPT = """请只根据这张真实浏览器截图检查图面。按 JSON 返回，不要猜测截图外的信息。
检查：斜线箭头、折线是否过多、模块是否重叠/间距过小、文字是否溢出/拥挤、层级与对齐是否清楚、是否出现英文代码痕迹、标签是否压线或互相遮挡。
只描述可观察到的问题；无问题 verdict=pass，有问题 verdict=revise。能确定时给出具体节点/连线 ID 和 adjustment。
允许 adjustment 类型：increase_spacing（axis: x|y, factor: 1.1-2）、move_node（nodeId, x, y）、edit_text（nodeId, field: title|desc, value）、split_required（reason）。
JSON 格式：{"verdict":"pass|revise","issues":[{"code":"...","description":"...","nodeId":"可选","edgeId":"可选"}],"adjustments":[...]}。
截图之外的代码职责、证据正确性不能靠视觉判断；这些由几何检查和源码证据校验负责。
"""


def apply_review(diagram: dict, review: dict) -> tuple[dict, list[str]]:
    updated = copy.deepcopy(diagram)
    notes: list[str] = []
    adjustments = review.get("adjustments", []) if isinstance(review, dict) else []
    nodes = {node["id"]: node for node in updated["nodes"]}
    for item in adjustments:
        kind = item.get("type")
        if kind == "increase_spacing":
            axis = item.get("axis", "x")
            if axis not in {"x", "y"}:
                notes.append("忽略未知的留白方向")
                continue
            factor = min(2.0, max(1.1, float(item.get("factor", 1.2))))
            options = updated.setdefault("layout", {})
            key = "gapX" if axis == "x" else "gapY"
            default = 36 if axis == "x" else 18
            options[key] = int(options.get(key, default) * factor)
            notes.append(f"已将{ '水平' if axis == 'x' else '垂直' }间距调整为 {options[key]} 像素")
        elif kind == "move_node" and item.get("nodeId") in nodes:
            node = nodes[item["nodeId"]]
            pos = node.setdefault("position", {})
            pos.update({axis: float(item[axis]) for axis in ("x", "y") if axis in item})
            notes.append(f"已固定模块「{node['title']}」位置")
        elif kind == "edit_text" and item.get("nodeId") in nodes and item.get("field") in {"title", "desc"}:
            nodes[item["nodeId"]][item["field"]] = str(item.get("value", ""))
            notes.append(f"已更新模块「{nodes[item['nodeId']]['title']}」文案")
        elif kind == "split_required":
            notes.append(f"需要用户决定拆图：{item.get('reason', '视觉复杂度过高')}")
        else:
            notes.append(f"未应用未知或无法定位的修正：{kind}")
    return updated, notes


def _views(diagram: dict, *, inherited_architecture: bool = False):
    architecture_context = inherited_architecture or diagram.get("type") == "architecture"
    yield diagram, architecture_context and diagram.get("type") == "flow"
    for child in diagram.get("subDiagrams", []):
        yield from _views(child, inherited_architecture=architecture_context)


def _replace_view(root: dict, view_id: str, replacement: dict) -> bool:
    if root["id"] == view_id:
        root.clear()
        root.update(replacement)
        return True
    for child in root.get("subDiagrams", []):
        if _replace_view(child, view_id, replacement):
            return True
    return False


def _safe_stem(value: str) -> str:
    return re.sub(r"[^\w-]+", "-", value).strip("-") or "subdiagram"


def run_review_loop(diagram: dict, output_dir: str | Path, *, reviewer: Callable[[Path, str, dict], dict] | None,
                    max_rounds: int = 4, browser_executable: str | None = None) -> dict:
    """为主图和全部子图截图、几何检查，并通过 callback 逐图请求视觉判断，最多迭代 4 次。

    reviewer(image_path, review_prompt, geometry_report) 必须返回结构化视觉评估。
    没有 reviewer 时为每个视图生成待审请求，绝不伪报通过。
    """
    if max_rounds < 1 or max_rounds > 4:
        raise ValueError("max_rounds 必须在 1 到 4 之间")
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    current = copy.deepcopy(require_valid_diagram(diagram))
    history = []
    for round_no in range(1, max_rounds + 1):
        round_views = []
        for view, hardcoded_ports in list(_views(current)):
            stem = "main" if view["id"] == current["id"] else _safe_stem(view["id"])
            prefix = root / f"round-{round_no:02d}-{stem}"
            layout = layout_diagram(view, backend="builtin" if hardcoded_ports else "auto",
                                    hardcoded_ports=hardcoded_ports)
            html_path, image_path = prefix.with_suffix(".html"), prefix.with_suffix(".png")
            html_path.write_text(render_html(view, layout, architecture_detail=hardcoded_ports), encoding="utf-8")
            capture = capture_html(html_path, image_path, browser_executable=browser_executable)
            write_capture_report(capture, prefix.with_name(prefix.name + "-capture.json"))
            geometry = quality_report(view, layout, hardcoded_ports=hardcoded_ports)
            if reviewer is None:
                request = {"round": round_no, "diagramId": view["id"], "image": str(image_path),
                           "geometry": geometry, "prompt": REVIEW_PROMPT}
                prefix.with_name(prefix.name + "-visual-review-request.json").write_text(
                    json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
                visual = {"verdict": "pending"}
            else:
                visual = reviewer(image_path, REVIEW_PROMPT, geometry)
            round_views.append({"diagramId": view["id"], "geometry": geometry, "visual": visual,
                                "screenshot": str(image_path), "capture": capture})

        history.append({"round": round_no, "views": round_views})
        if reviewer is None:
            return {"status": "pending_visual_review", "diagram": current, "history": history,
                    "next_action": "逐张查看主图与所有子图截图，按各自审查请求生成 JSON，再调用 apply_review。"}

        all_passed = True
        for item in round_views:
            visual, geometry, capture = item["visual"], item["geometry"], item["capture"]
            capture_passed = not capture["page_errors"] and not capture["dom"].get("textOverflow")
            if visual.get("verdict") == "pass" and geometry["passed"] and capture_passed:
                continue
            all_passed = False
            if any(adjustment.get("type") == "split_required" for adjustment in visual.get("adjustments", [])):
                return {"status": "awaiting_user_decision", "diagram": current, "history": history,
                        "next_action": "图面密度仍需拆图或聚焦，请交由用户选择。"}
            if visual.get("verdict") not in {"pass", "revise"}:
                continue
            target = next((view for view in _views(current) if view["id"] == item["diagramId"]), None)
            if target:
                updated, notes = apply_review(target, visual)
                _replace_view(current, target["id"], updated)
                item["applied_adjustments"] = notes
        errors = __import__("architecture_diagram.models", fromlist=["validate_diagram"]).validate_diagram(current)
        if errors:
            history[-1]["validation_errors"] = errors
            return {"status": "invalid_after_review", "diagram": current, "history": history}
        if all_passed:
            layout = layout_diagram(current)
            final_html, final_svg = root / "architecture-diagram.html", root / "architecture-diagram.svg"
            final_html.write_text(render_html(current, layout), encoding="utf-8")
            final_svg.write_text(render_svg(current, layout), encoding="utf-8")
            summary = {"status": "passed", "rounds": round_no, "history": history,
                       "outputs": {"html": str(final_html), "svg": str(final_svg),
                                   "pngs": [item["screenshot"] for item in round_views]}}
            (root / "visual-review-report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            return summary
    return {"status": "max_rounds_reached", "diagram": current, "history": history,
            "next_action": "请查看最后一轮主图与所有子图截图；仍不清晰时拆图或聚焦后重跑。"}
