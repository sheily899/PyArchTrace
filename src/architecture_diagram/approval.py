"""结构审阅与显式用户确认凭据。"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from .analysis_audit import audit_analysis
from .details import details_consistency_errors
from .layout import layout_diagram
from .models import validate_diagram
from .quality import content_density_report, quality_report


def _walk(diagram: dict, *, architecture_parent: bool = False):
    current_is_architecture = architecture_parent or diagram.get("type") == "architecture"
    for child in diagram.get("subDiagrams", []):
        hardcoded = current_is_architecture and child.get("type") == "flow"
        yield child, hardcoded
        yield from _walk(child, architecture_parent=current_is_architecture)


def inspect_structure(analysis: dict, diagram: dict, *, source_root: str | Path | None = None,
                      backend: str = "builtin", facts: dict | None = None,
                      work_cache=None) -> dict[str, Any]:
    """不写图文件，执行结构、几何与内容密度审阅。"""
    cache_key = (work_cache.audit_key(analysis, diagram, facts, source_root, backend)
                 if work_cache is not None else None)
    if work_cache is not None:
        cached_report = work_cache.get_audit(cache_key)
        if cached_report is not None:
            return work_cache.with_stats(cached_report)

    errors = (work_cache.validate(diagram, validate_diagram)
              if work_cache is not None else validate_diagram(diagram))
    analysis_report = audit_analysis(analysis, diagram, source_root=source_root)
    for error in errors:
        analysis_report["errors"].append(f"diagram: {error}")
    if errors:
        analysis_report["passed"] = False

    layout_failures: list[dict[str, str]] = []
    try:
        root_layout = (work_cache.layout(diagram, backend=backend) if work_cache is not None
                       else layout_diagram(diagram, backend=backend))
        root_geometry = quality_report(diagram, root_layout)
    except (ValueError, KeyError, TypeError) as exc:
        message = str(exc)
        layout_failures.append({"graph": diagram.get("id", "main"), "message": message})
        analysis_report["errors"].append(f"layout: {message}")
        analysis_report["passed"] = False
        root_layout = {"width": 1440, "height": 800, "nodes": [], "layers": [], "edges": [],
                       "groupFrames": [], "template": diagram.get("template")}
        root_geometry = {"passed": False, "issues": [{"code": "layout_failed", "message": message}],
                         "counts": {}, "canvas": {"width": 1440, "height": 800, "aspectRatio": 1.8}}
    sub_layouts: dict[str, dict] = {}
    sub_geometry: dict[str, dict] = {}
    for child, hardcoded in _walk(diagram):
        child_backend = "builtin" if hardcoded else backend
        try:
            layout = (work_cache.layout(child, backend=child_backend, hardcoded_ports=hardcoded)
                      if work_cache is not None else
                      layout_diagram(child, backend=child_backend, hardcoded_ports=hardcoded))
            sub_layouts[child["id"]] = layout
            sub_geometry[child["id"]] = quality_report(child, layout, hardcoded_ports=hardcoded)
        except (ValueError, KeyError, TypeError) as exc:
            message = str(exc)
            layout_failures.append({"graph": child.get("id", "unknown"), "message": message})
            analysis_report["errors"].append(f"layout {child.get('id', 'unknown')}: {message}")
            analysis_report["passed"] = False
            sub_layouts[child["id"]] = {"width": 1, "height": 1, "nodes": [], "layers": [], "edges": []}
            sub_geometry[child["id"]] = {"passed": False,
                                          "issues": [{"code": "layout_failed", "message": message}],
                                          "counts": {}, "canvas": {"width": 1, "height": 1, "aspectRatio": 1}}
    density = content_density_report(diagram, root_layout, analysis=analysis, sub_layouts=sub_layouts)
    if diagram.get("type") == "architecture":
        if facts is None:
            analysis_report["errors"].append("架构图审阅必须提供 scan 事实清单，以核对详情派生字段")
            analysis_report["passed"] = False
        else:
            try:
                detail_errors = details_consistency_errors(diagram, analysis, facts)
            except ValueError as exc:
                detail_errors = [str(exc)]
            for error in detail_errors:
                analysis_report["errors"].append(error)
            if detail_errors:
                analysis_report["passed"] = False
    geometry_passed = root_geometry["passed"] and all(report["passed"] for report in sub_geometry.values())
    passed = analysis_report["passed"] and geometry_passed and density["passed"]
    report = {
        "passed": passed,
        "requiresUserConfirmation": True,
        "analysisAudit": analysis_report,
        "geometry": {"passed": geometry_passed, "root": root_geometry, "subdiagrams": sub_geometry},
        "contentDensity": density,
        "layoutFailures": layout_failures,
        "layoutSummary": {
            "mainCanvasWidth": root_layout.get("width"),
            "mainCanvasHeight": root_layout.get("height"),
            "aspectRatio": round(root_layout.get("width", 0) / max(1, root_layout.get("height", 1)), 3),
            "template": root_layout.get("template", diagram.get("template")),
            "templateReason": root_layout.get("templateReason"),
            "mainModuleCount": len(diagram.get("nodes", [])),
            "mainEdgeCount": len(root_layout.get("edges", [])),
            "layerModuleCounts": {
                layer.get("name", layer.get("id")): sum(1 for node in root_layout.get("nodes", [])
                                                         if node.get("layer") == layer.get("id"))
                for layer in root_layout.get("layers", [])
            },
            "sourceLayerModuleCounts": {
                layer.get("name", layer.get("id")): sum(1 for node in diagram.get("nodes", [])
                                                         if node.get("layer") == layer.get("id"))
                for layer in diagram.get("layers", [])
            },
            "mainChain": root_layout.get("mainChain", []),
        },
    }
    if work_cache is not None:
        work_cache.set_audit(cache_key, report)
        return work_cache.with_stats(report)
    return report


def _canonical_digest(path: str | Path) -> str:
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def input_digests(analysis_path: str | Path, diagram_path: str | Path, facts_path: str | Path) -> dict[str, str]:
    return {
        "analysisSha256": _canonical_digest(analysis_path),
        "diagramSha256": _canonical_digest(diagram_path),
        "factsSha256": _canonical_digest(facts_path),
    }


def write_approval(analysis_path: str | Path, diagram_path: str | Path, output: str | Path,
                   *, confirmation: str, source_root: str | Path | None = None,
                   backend: str = "builtin", facts_path: str | Path,
                   review_path: str | Path, work_cache=None) -> dict[str, Any]:
    if confirmation != "确认":
        raise ValueError("必须收到用户明确回复“确认”后才能写入结构确认凭据")
    review = json.loads(Path(review_path).read_text(encoding="utf-8-sig"))
    expected_digests = input_digests(analysis_path, diagram_path, facts_path)
    if review.get("passed") is not True or review.get("requiresUserConfirmation") is not True:
        raise ValueError("结构审阅报告不存在、未通过或不是待用户确认报告")
    if review.get("inputDigests") != expected_digests:
        raise ValueError("结构审阅报告与当前 analysis/diagram/facts 不匹配；请重新审阅")
    analysis = json.loads(Path(analysis_path).read_text(encoding="utf-8-sig"))
    diagram = json.loads(Path(diagram_path).read_text(encoding="utf-8-sig"))
    facts = json.loads(Path(facts_path).read_text(encoding="utf-8-sig"))
    report = inspect_structure(analysis, diagram, source_root=source_root, backend=backend,
                               facts=facts, work_cache=work_cache)
    if not report["passed"]:
        raise ValueError("结构、几何或内容密度审阅未通过；不能签发确认凭据")
    receipt = {
        "schemaVersion": 1,
        "status": "approved",
        "confirmedAt": datetime.now(timezone.utc).isoformat(),
        **expected_digests,
        "reviewSha256": _canonical_digest(review_path),
    }
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt


def verify_approval(analysis_path: str | Path, diagram_path: str | Path,
                    approval_path: str | Path | None, facts_path: str | Path | None = None,
                    review_path: str | Path | None = None) -> None:
    if approval_path is None:
        raise ValueError("架构图渲染需要 --analysis 与经用户确认生成的 --approval 凭据")
    receipt = json.loads(Path(approval_path).read_text(encoding="utf-8-sig"))
    if receipt.get("schemaVersion") != 1 or receipt.get("status") != "approved":
        raise ValueError("结构确认凭据格式无效")
    if receipt.get("analysisSha256") != _canonical_digest(analysis_path):
        raise ValueError("analysis.json 已变化；请重新审阅并等待用户确认")
    if receipt.get("diagramSha256") != _canonical_digest(diagram_path):
        raise ValueError("diagram.json 已变化；请重新审阅并等待用户确认")
    if facts_path is None or receipt.get("factsSha256") != _canonical_digest(facts_path):
        raise ValueError("facts.json 缺失或已变化；请重新审阅并等待用户确认")
    if review_path is None or receipt.get("reviewSha256") != _canonical_digest(review_path):
        raise ValueError("结构审阅报告缺失或已变化；请重新审阅并等待用户确认")
    review = json.loads(Path(review_path).read_text(encoding="utf-8-sig"))
    if review.get("passed") is not True or review.get("inputDigests") != input_digests(analysis_path, diagram_path, facts_path):
        raise ValueError("结构审阅报告未通过或与当前输入不匹配")
