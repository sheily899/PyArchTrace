"""architecture-diagram 命令行入口。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .analysis_audit import audit_analysis
from .analysis_reports import generate_analysis_reports
from .approval import input_digests, inspect_structure, verify_approval, write_approval
from .capture import capture_html, write_capture_report
from .details import details_consistency_errors, enrich_diagram_details
from .layout import layout_diagram
from .models import validate_diagram
from .quality import content_density_report, quality_report
from .render import render_html, render_svg
from .review import REVIEW_PROMPT, apply_review, run_review_loop
from .scanner import scan_project
from .versioning import version_mismatches
from .work_cache import WorkCache
from .work_orders import build_work_order


def _read_json(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _write_json(path: str | Path, value) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _schema_path() -> Path:
    candidates = [
        Path(__file__).resolve().parents[2] / "schemas" / "diagram.schema.json",
        Path(sys.prefix) / "share" / "architecture-diagram" / "schemas" / "diagram.schema.json",
    ]
    return next((candidate for candidate in candidates if candidate.is_file()), candidates[0])


def _analysis_schema_path() -> Path:
    candidates = [
        Path(__file__).resolve().parents[2] / "schemas" / "analysis.schema.json",
        Path(sys.prefix) / "share" / "architecture-diagram" / "schemas" / "analysis.schema.json",
    ]
    return next((candidate for candidate in candidates if candidate.is_file()), candidates[0])


def _walk_subdiagrams(diagram: dict, *, inherited_architecture: bool = False):
    architecture_context = inherited_architecture or diagram.get("type") == "architecture"
    for child in diagram.get("subDiagrams", []):
        hardcoded_ports = architecture_context and child.get("type") == "flow"
        yield child, hardcoded_ports
        yield from _walk_subdiagrams(child, inherited_architecture=architecture_context)


def _work_cache_for(path: str | Path, enabled: bool) -> WorkCache | None:
    if not enabled:
        return None
    return WorkCache(Path(path).resolve().parent / ".architecture-diagram-cache")


def _cmd_scan(args) -> int:
    facts = scan_project(args.project, excluded_dirs=set(args.exclude_dir or []),
                         included_dirs=set(args.include_dir or []),
                         optimized=getattr(args, "optimized_scan", False))
    _write_json(args.output, facts)
    print(
        f"已盘点 {facts['inventory']['fileCount']} 个项目文件；"
        f"提取 {facts['summary']['python_files']} 个 Python 文件的 AST，共 "
        f"{facts['summary']['code_lines']} 行 Python 代码。非 Python 文件仅作路径盘点，不纳入语义分析。"
    )
    print(f"事实清单：{Path(args.output).resolve()}")
    if "scanConfig" in facts:
        print(f"扫描模式：优化模式（{facts['exclusionRulesVersion']}）")
        print(f"配置排除目录名：{', '.join(facts['scanConfig']['excludedDirectoryNames'])}")
    print(f"实际跳过路径：{', '.join(facts['inventory']['excludedPaths']) or '无'}")
    print("注意：AST 事实不能证明业务职责、运行时调用关系或调用成功；请基于源码补齐证据。")
    return 0


def _cmd_prompt(args) -> int:
    facts = _read_json(args.facts)
    schema_path = _schema_path()
    if not schema_path.is_file():
        raise FileNotFoundError("未找到 diagram.schema.json；请从项目工作区运行或检查安装包的 share/architecture-diagram/schemas 目录")
    analysis_schema_path = _analysis_schema_path()
    if not analysis_schema_path.is_file():
        raise FileNotFoundError("未找到 analysis.schema.json；请从项目工作区运行或检查安装包的 share/architecture-diagram/schemas 目录")
    analysis = _read_json(args.analysis) if getattr(args, "analysis", None) else None
    prompt = build_work_order(
        facts=facts,
        analysis_schema=json.loads(analysis_schema_path.read_text(encoding="utf-8")),
        diagram_schema=json.loads(schema_path.read_text(encoding="utf-8")),
        stage=getattr(args, "stage", None),
        analysis=analysis,
        module_id=getattr(args, "module_id", None),
        slim=getattr(args, "slim_input", False),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(prompt, encoding="utf-8")
    print(f"语义抽象工作单：{output.resolve()}")
    print(f"工作单字节数：{len(prompt.encode('utf-8'))}")
    print(f"输入模式：{'阶段筛选' if getattr(args, 'slim_input', False) else '完整兼容'}")
    return 0


def _cmd_analysis_reports(args) -> int:
    analysis = _read_json(args.analysis)
    reports = generate_analysis_reports(analysis)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in reports.items():
        path = output_dir / name
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
        print(f"{name}：{path.resolve()}")
    return 0


def _cmd_validate(args) -> int:
    diagram = _read_json(args.diagram)
    cache = _work_cache_for(args.diagram, getattr(args, "reuse_layout_cache", False))
    errors = cache.validate(diagram, validate_diagram) if cache else validate_diagram(diagram)
    if getattr(args, "check_versions", False):
        errors.extend(version_mismatches(getattr(args, "skill_file", None)))
    if errors:
        print("图数据校验未通过：")
        for error in errors:
            print(f"- {error}")
        return 2
    print("图数据校验通过。")
    return 0


def _cmd_audit_analysis(args) -> int:
    analysis = _read_json(args.analysis)
    diagram = _read_json(args.diagram)
    cache = _work_cache_for(args.diagram, getattr(args, "reuse_layout_cache", False))
    report = (inspect_structure(analysis, diagram, source_root=args.source_root,
                                backend=args.layout_backend, facts=_read_json(args.facts), work_cache=cache)
              if diagram.get("type") == "architecture" and args.facts else
              audit_analysis(analysis, diagram, source_root=args.source_root))
    if diagram.get("type") == "architecture" and not args.facts:
        report["passed"] = False
        report.setdefault("errors", []).append("架构图内容审计必须提供 scan 生成的 --facts")
    diagram_errors = cache.validate(diagram, validate_diagram) if cache else validate_diagram(diagram)
    if diagram_errors:
        report["passed"] = False
        report.setdefault("errors", []).extend(f"diagram: {error}" for error in diagram_errors)
    if args.output:
        _write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 2


def _cmd_review_structure(args) -> int:
    analysis = _read_json(args.analysis)
    diagram = _read_json(args.diagram)
    cache = _work_cache_for(args.diagram, getattr(args, "reuse_layout_cache", False))
    report = inspect_structure(analysis, diagram, source_root=args.source_root,
                               backend=args.layout_backend, facts=_read_json(args.facts), work_cache=cache)
    modules = analysis.get("stageB", {}).get("modules", [])
    module_by_id = {item.get("id"): item for item in modules if isinstance(item, dict)}
    print("| ID | 模块 | 所属层 | 主图说明 | 证据路径 |")
    print("|---|---|---|---|---|")
    layers = {item.get("id"): item.get("name") for item in analysis.get("stageB", {}).get("layers", [])}
    v2 = ("template" in diagram or
          (isinstance(diagram.get("layout"), dict) and diagram["layout"].get("contractVersion") == 2))
    for node in diagram.get("nodes", []):
        module = module_by_id.get(node.get("id"), {})
        evidence = "、".join(item.get("path", "") for item in module.get("evidence", []))
        print(f"| {node.get('id')} | {node.get('title')} | {layers.get(node.get('layer'), node.get('layer'))} | {node.get('desc', '')} | {evidence} |")
    print("\n层间主流向：")
    if v2:
        display_names = {layer.get("id"): layer.get("name") for layer in diagram.get("layers", [])}
        display_names.update({item.get("id"): item.get("name") for item in diagram.get("layout", {}).get("layerMerges", [])})
        display_names.update({item.get("id"): item.get("name") for item in diagram.get("layout", {}).get("pipelineGroups", [])})
        display_names.update({key: value.get("name") for key, value in diagram.get("layout", {}).get("kernelGroups", {}).items()})
        display_names.update({item.get("id"): item.get("name") for item in diagram.get("layout", {}).get("deploymentZones", [])})
        for flow in diagram.get("layerFlows", []):
            print(f"- {display_names.get(flow.get('fromLayer'), flow.get('fromLayer'))} → {display_names.get(flow.get('toLayer'), flow.get('toLayer'))}（{flow.get('label', '')}）")
        merge = diagram.get("layout", {}).get("pipelineMerge")
        if merge:
            print(f"- {display_names.get(merge.get('from'), merge.get('from'))} → {display_names.get(merge.get('to'), merge.get('to'))}（{merge.get('label', '汇合')}）")
        if not diagram.get("layerFlows") and not merge:
            print("- 未发现可在主图展示且有证据的层间流向")
    else:
        for edge in diagram.get("edges", []):
            left, right = next((n for n in diagram.get("nodes", []) if n.get("id") == edge.get("from")), {}), next((n for n in diagram.get("nodes", []) if n.get("id") == edge.get("to")), {})
            print(f"- {layers.get(left.get('layer'), left.get('layer'))} → {layers.get(right.get('layer'), right.get('layer'))}（{left.get('title')} → {right.get('title')}）")
    print("\n主链路：")
    if v2 and diagram.get("mainChain"):
        node_titles = {node.get("id"): node.get("title") for node in diagram.get("nodes", [])}
        print("- " + " → ".join(node_titles.get(node_id, node_id) for node_id in diagram["mainChain"]))
    else:
        for path in analysis.get("stageD", {}).get("paths", []):
            names = [module_by_id.get(node_id, {}).get("title", node_id) for node_id in path.get("nodeIds", [])]
            print(f"- {path.get('title')}: " + " → ".join(names))
    print("\n覆盖范围：")
    print(json.dumps(analysis.get("coverage", {}), ensure_ascii=False, indent=2))
    print(f"\n审阅状态：{'通过' if report['passed'] else '未通过'}；软约束警告 {len(report['contentDensity']['warnings'])} 条")
    for warning in report["contentDensity"]["warnings"]:
        print(f"- {warning['message']}")
    print("结构已生成并审阅；当前命令不会渲染图。等待用户明确确认后再运行 approve-structure。")
    report["structureConfirmationRequired"] = True
    report["moduleTable"] = [
            {"id": node.get("id"), "title": node.get("title"), "layer": layers.get(node.get("layer")),
             "description": node.get("desc"), "evidence": module_by_id.get(node.get("id"), {}).get("evidence", [])}
            for node in diagram.get("nodes", [])
        ]
    report["layerFlows"] = ([
            {"from": edge.get("fromLayer"), "to": edge.get("toLayer"), "label": edge.get("label"),
             "evidence": edge.get("evidence", [])}
            for edge in diagram.get("layerFlows", [])
        ] if v2 else [
            {"from": edge.get("from"), "to": edge.get("to"),
             "fromLayer": layers.get(next((n.get("layer") for n in diagram.get("nodes", []) if n.get("id") == edge.get("from")), "")),
             "toLayer": layers.get(next((n.get("layer") for n in diagram.get("nodes", []) if n.get("id") == edge.get("to")), ""))}
            for edge in diagram.get("edges", [])
        ])
    report["mainPaths"] = ([{"nodeIds": diagram.get("mainChain", [])}] if v2
                            else analysis.get("stageD", {}).get("paths", []))
    report["coverage"] = analysis.get("coverage", {})
    report["inputDigests"] = input_digests(args.analysis, args.diagram, args.facts)
    _write_json(args.output, report)
    print(f"结构审阅报告：{Path(args.output).resolve()}")
    return 0 if report["passed"] else 2


def _cmd_approve_structure(args) -> int:
    cache = _work_cache_for(args.diagram, getattr(args, "reuse_layout_cache", False))
    receipt = write_approval(args.analysis, args.diagram, args.output,
                              confirmation=args.confirmation, source_root=args.source_root,
                              backend=args.layout_backend, facts_path=args.facts, review_path=args.review,
                              work_cache=cache)
    print(f"已记录结构确认凭据：{Path(args.output).resolve()}")
    print(f"IR 摘要：analysis={receipt['analysisSha256'][:12]} diagram={receipt['diagramSha256'][:12]}")
    return 0


def _cmd_render(args) -> int:
    diagram = _read_json(args.diagram)
    cache = _work_cache_for(args.diagram, getattr(args, "reuse_layout_cache", False))
    errors = cache.validate(diagram, validate_diagram) if cache else validate_diagram(diagram)
    if errors:
        print("图数据校验未通过：" + "；".join(errors), file=sys.stderr)
        return 2
    analysis = None
    facts = None
    review = None
    if diagram.get("type") == "architecture":
        if not args.analysis or not args.facts or not args.review:
            print("架构图必须提供 analysis.json、facts.json、结构审阅报告，并先完成人工结构确认。", file=sys.stderr)
            return 2
        try:
            verify_approval(args.analysis, args.diagram, args.approval, args.facts, args.review)
            analysis = _read_json(args.analysis)
            facts = _read_json(args.facts)
            review = inspect_structure(analysis, diagram, source_root=args.source_root,
                                       backend=args.layout_backend, facts=facts, work_cache=cache)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"渲染已阻止：{exc}", file=sys.stderr)
            return 2
        if not review["passed"]:
            print("渲染已阻止：结构、几何或内容密度审阅未通过。", file=sys.stderr)
            return 2
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    svg_path = out / "architecture-diagram.svg"
    html_path = out / "architecture-diagram.html"
    sub_layouts: dict[str, dict] = {}
    sub_hardcoded: dict[str, bool] = {}
    view_layouts: dict[str, dict] = {}

    if cache is not None:
        layout = cache.layout(diagram, backend=args.layout_backend)
        for child, hardcoded_ports in _walk_subdiagrams(diagram):
            child_backend = "builtin" if hardcoded_ports else args.layout_backend
            sub_layouts[child["id"]] = cache.layout(child, backend=child_backend,
                                                       hardcoded_ports=hardcoded_ports)
            sub_hardcoded[child["id"]] = hardcoded_ports
        view_layouts = {diagram.get("id"): layout, **sub_layouts}
        svg_path.write_text(render_svg(diagram, layout,
                                      include_drilldown=diagram.get("type") != "architecture"), encoding="utf-8")
        html_path.write_text(render_html(diagram, layout, backend=args.layout_backend,
                                         precomputed_layouts=view_layouts), encoding="utf-8")
        report = json.loads(json.dumps(review["geometry"]["root"], ensure_ascii=False)) if review else None
        sub_reports = (json.loads(json.dumps(review["geometry"]["subdiagrams"], ensure_ascii=False))
                       if review else {})
        if report is None:
            report = quality_report(diagram, layout)
            sub_reports = {
                child["id"]: quality_report(child, sub_layouts[child["id"]],
                                             hardcoded_ports=sub_hardcoded[child["id"]])
                for child, _ in _walk_subdiagrams(diagram)
            }
    else:
        layout = layout_diagram(diagram, backend=args.layout_backend)
        svg_path.write_text(render_svg(diagram, layout,
                                      include_drilldown=diagram.get("type") != "architecture"), encoding="utf-8")
        html_path.write_text(render_html(diagram, layout, backend=args.layout_backend), encoding="utf-8")
        report = quality_report(diagram, layout)
        sub_reports = {}
        for child, hardcoded_ports in _walk_subdiagrams(diagram):
            child_backend = "builtin" if hardcoded_ports else args.layout_backend
            child_layout = layout_diagram(child, backend=child_backend, hardcoded_ports=hardcoded_ports)
            sub_reports[child["id"]] = quality_report(child, child_layout, hardcoded_ports=hardcoded_ports)
            sub_hardcoded[child["id"]] = hardcoded_ports
    if sub_reports:
        report["subdiagrams"] = sub_reports
        report["passed"] = report["passed"] and all(item["passed"] for item in sub_reports.values())
    if analysis is not None:
        density = (review["contentDensity"] if cache is not None else
                   content_density_report(diagram, layout, analysis=analysis,
                                          sub_layouts={child["id"]: layout_diagram(
                                              child, backend="builtin" if hardcoded else args.layout_backend,
                                              hardcoded_ports=hardcoded)
                                              for child, hardcoded in _walk_subdiagrams(diagram)}))
        report["contentDensity"] = density
        report["passed"] = report["passed"] and density["passed"]
        _write_json(out / "content-density-report.json", density)
    if cache is not None:
        report["workCache"] = cache.stats()
    _write_json(out / "geometry-report.json", report)
    print(f"SVG：{svg_path.resolve()}")
    print(f"HTML：{html_path.resolve()}")
    print(f"布局后端：{layout.get('backend', 'builtin-layered')}")
    if layout.get("backend_warning"):
        print(f"布局说明：{layout['backend_warning']}")
    print(f"几何检查：{'通过' if report['passed'] else '发现问题'}（{len(report['issues'])} 项）")
    if args.capture:
        png_path = out / "architecture-diagram.png"
        capture = capture_html(html_path, png_path, browser_executable=args.browser,
                               viewport=(args.viewport_width, args.viewport_height), scale=args.scale,
                               omit_drill_icons=diagram.get("type") == "architecture")
        write_capture_report(capture, out / "capture-report.json")
        print(f"截图：{png_path.resolve()}（真实 file:// 浏览器渲染）")
        for child, hardcoded_ports in _walk_subdiagrams(diagram):
            safe_id = re.sub(r"[^\w-]+", "-", child["id"]).strip("-") or "subdiagram"
            child_backend = "builtin" if hardcoded_ports else args.layout_backend
            child_layout = (sub_layouts[child["id"]] if cache is not None else
                            layout_diagram(child, backend=child_backend, hardcoded_ports=hardcoded_ports))
            child_html = out / f"subdiagram-{safe_id}.html"
            child_svg = out / f"subdiagram-{safe_id}.svg"
            child_png = out / f"subdiagram-{safe_id}.png"
            if cache is not None:
                child_html.write_text(render_html(child, child_layout, backend=child_backend,
                                                  architecture_detail=hardcoded_ports,
                                                  precomputed_layouts=view_layouts), encoding="utf-8")
            else:
                child_html.write_text(render_html(child, child_layout, backend=child_backend,
                                                  architecture_detail=hardcoded_ports), encoding="utf-8")
            child_svg.write_text(render_svg(child, child_layout), encoding="utf-8")
            child_capture = capture_html(child_html, child_png, browser_executable=args.browser,
                                         viewport=(args.viewport_width, args.viewport_height), scale=args.scale)
            write_capture_report(child_capture, out / f"subdiagram-{safe_id}-capture.json")
            print(f"下钻图截图：{child_png.resolve()}（几何检查：{'通过' if sub_reports[child['id']]['passed'] else '发现问题'}）")
    return 0


def _cmd_enrich_details(args) -> int:
    analysis = _read_json(args.analysis)
    diagram = _read_json(args.diagram)
    facts = _read_json(args.facts)
    enriched = enrich_diagram_details(diagram, analysis, facts)
    _write_json(args.output, enriched)
    print(f"已从证据关系和 AST 事实补齐详情派生字段：{Path(args.output).resolve()}")
    return 0


def _cmd_capture(args) -> int:
    html_source = Path(args.html).read_text(encoding="utf-8-sig")
    if 'class="architecture-only"' in html_source:
        if not all((args.analysis, args.diagram, args.facts, args.review, args.approval)):
            print("架构图截图必须提供匹配的 analysis、diagram、facts、review 和 approval。", file=sys.stderr)
            return 2
        try:
            verify_approval(args.analysis, args.diagram, args.approval, args.facts, args.review)
            cache = _work_cache_for(args.diagram, getattr(args, "reuse_layout_cache", False))
            audit = inspect_structure(_read_json(args.analysis), _read_json(args.diagram),
                                      source_root=args.source_root, facts=_read_json(args.facts),
                                      work_cache=cache)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"截图已阻止：{exc}", file=sys.stderr)
            return 2
        if not audit["passed"]:
            print("截图已阻止：结构、几何或内容密度审阅未通过。", file=sys.stderr)
            return 2
    report = capture_html(args.html, args.png, browser_executable=args.browser,
                          viewport=(args.viewport_width, args.viewport_height), scale=args.scale)
    report_path = args.report or str(Path(args.png).with_suffix(".capture.json"))
    write_capture_report(report, report_path)
    print(f"截图：{Path(args.png).resolve()}")
    print(f"报告：{Path(report_path).resolve()}")
    return 0 if not report["page_errors"] and not report["dom"].get("textOverflow") else 3


def _cmd_review_loop(args) -> int:
    diagram = _read_json(args.diagram)
    if diagram.get("type") == "architecture":
        if not args.analysis or not args.approval or not args.facts or not args.review:
            print("架构图视觉审查必须提供 analysis、facts、结构审阅报告和用户确认凭据；确认前不生成截图。", file=sys.stderr)
            return 2
        try:
            verify_approval(args.analysis, args.diagram, args.approval, args.facts, args.review)
            cache = _work_cache_for(args.diagram, getattr(args, "reuse_layout_cache", False))
            report = inspect_structure(_read_json(args.analysis), diagram, source_root=args.source_root,
                                      backend=args.layout_backend, facts=_read_json(args.facts),
                                      work_cache=cache)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"视觉审查已阻止：{exc}", file=sys.stderr)
            return 2
        if not report["passed"]:
            print("视觉审查已阻止：结构、几何或内容密度审阅未通过。", file=sys.stderr)
            return 2
    result = run_review_loop(diagram, args.output_dir, reviewer=None, max_rounds=args.max_rounds,
                             browser_executable=args.browser)
    print(json.dumps({"status": result["status"], "history": result["history"], "next_action": result.get("next_action")},
                     ensure_ascii=False, indent=2))
    return 0


def _cmd_apply_review(args) -> int:
    diagram = _read_json(args.diagram)
    review = _read_json(args.review)
    updated, notes = apply_review(diagram, review)
    errors = validate_diagram(updated)
    if errors:
        print("修正後未通過校驗：" + "；".join(errors), file=sys.stderr)
        return 2
    _write_json(args.output, updated)
    _write_json(str(Path(args.output).with_suffix(".adjustments.json")), {"notes": notes, "review": review})
    print(f"已套用 {len(review.get('adjustments', []))} 項修正：{Path(args.output).resolve()}")
    for note in notes:
        print(f"- {note}")
    return 0


def _cmd_review_prompt(args) -> int:
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(REVIEW_PROMPT + "\n\n请把评估结果另存为 JSON，再通过 architecture-diagram apply-review 应用修正。\n", encoding="utf-8")
    print(f"视觉审查提示：{target.resolve()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="architecture-diagram", description="基于 Python 项目源码证据生成中文架构、时序和链路图")
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="盘点 Python 项目并输出文件清单与 Python AST 结构事实 JSON")
    scan.add_argument("project")
    scan.add_argument("-o", "--output", required=True)
    scan.add_argument("--exclude-dir", action="append", help="追加跳过的目录名")
    scan.add_argument("--optimized-scan", action="store_true", help="启用单次遍历扫描与可配置排除规则（显式 opt-in）")
    scan.add_argument("--include-dir", action="append", help="优化模式下覆盖默认排除并重新包含该目录名")
    scan.set_defaults(func=_cmd_scan)
    prompt = sub.add_parser("abstract-prompt", help="根据事实 JSON 生成中文语义抽象工作单")
    prompt.add_argument("facts")
    prompt.add_argument("-o", "--output", required=True)
    prompt.add_argument("--slim-input", action="store_true", help="显式启用分阶段输入筛选；默认保持完整兼容工作单")
    prompt.add_argument("--stage", choices=["A", "B", "C", "D"], help="生成单阶段工作单；须同时启用 --slim-input")
    prompt.add_argument("--analysis", help="B/C/D 阶段所需的已有 analysis.json")
    prompt.add_argument("--module-id", help="C 阶段限定到单个模块")
    prompt.set_defaults(func=_cmd_prompt)
    reports = sub.add_parser("analysis-reports", help="从 analysis.json 生成模块、关系和主路径清单")
    reports.add_argument("analysis")
    reports.add_argument("-o", "--output-dir", required=True)
    reports.set_defaults(func=_cmd_analysis_reports)
    validate = sub.add_parser("validate", help="校验中间 JSON 与中文可见标签")
    validate.add_argument("diagram")
    validate.add_argument("--reuse-layout-cache", action="store_true", help="复用内容哈希匹配的校验结果")
    validate.add_argument("--check-versions", action="store_true", help="同时核对 Skill 文档与运行时代码版本")
    validate.add_argument("--skill-file", help="指定待核对的 Skill.md；默认检查当前源码或安装包文档")
    validate.set_defaults(func=_cmd_validate)
    audit = sub.add_parser("audit-analysis", help="审计候选、分层、关系与主链路，并核对图边覆盖")
    audit.add_argument("analysis", help="包含 stageA 至 stageD 的阶段化分析 JSON")
    audit.add_argument("diagram", help="对应图 JSON；每条边须引用 relationIds")
    audit.add_argument("--source-root", help="可选：本地源码根目录，用于核验路径和行号")
    audit.add_argument("--facts", help="scan 生成的事实清单；架构图内容密度审计必需")
    audit.add_argument("--layout-backend", choices=["auto", "builtin", "elkjs"], default="builtin")
    audit.add_argument("--reuse-layout-cache", action="store_true", help="复用内容、版本和源码证据均匹配的布局/审阅结果")
    audit.add_argument("-o", "--output", help="可选：写出机器审计报告 JSON")
    audit.set_defaults(func=_cmd_audit_analysis)
    review = sub.add_parser("review-structure", help="生成模块表、层间流向与硬/软约束审阅；不会渲染图")
    review.add_argument("analysis")
    review.add_argument("diagram")
    review.add_argument("--facts", required=True, help="scan 生成的事实清单，用于详情派生字段核验")
    review.add_argument("--source-root")
    review.add_argument("--layout-backend", choices=["auto", "builtin", "elkjs"], default="builtin")
    review.add_argument("--reuse-layout-cache", action="store_true", help="复用内容、版本和源码证据均匹配的布局/审阅结果")
    review.add_argument("-o", "--output", required=True, help="机器可读审阅报告")
    review.set_defaults(func=_cmd_review_structure)
    approve = sub.add_parser("approve-structure", help="在用户明确确认后签发绑定 IR/事实清单的凭据")
    approve.add_argument("analysis")
    approve.add_argument("diagram")
    approve.add_argument("--facts", required=True)
    approve.add_argument("--review", required=True, help="与当前 IR 摘要一致且审阅通过的报告")
    approve.add_argument("--confirmation", required=True, choices=["确认"], help="只能在用户明确回复确认后传入")
    approve.add_argument("--source-root")
    approve.add_argument("--layout-backend", choices=["auto", "builtin", "elkjs"], default="builtin")
    approve.add_argument("--reuse-layout-cache", action="store_true", help="复用内容、版本和源码证据均匹配的布局/审阅结果")
    approve.add_argument("-o", "--output", required=True)
    approve.set_defaults(func=_cmd_approve_structure)
    enrich = sub.add_parser("enrich-details", help="由代码事实补齐模块详情中的依赖、文件、技术栈与置信证据")
    enrich.add_argument("analysis")
    enrich.add_argument("diagram")
    enrich.add_argument("facts")
    enrich.add_argument("-o", "--output", required=True)
    enrich.set_defaults(func=_cmd_enrich_details)
    render = sub.add_parser("render", help="生成 SVG、可编辑单文件 HTML 和几何报告")
    render.add_argument("diagram")
    render.add_argument("-o", "--output-dir", required=True)
    render.add_argument("--capture", action="store_true", help="同时用真实浏览器截取 PNG")
    render.add_argument("--layout-backend", choices=["auto", "builtin", "elkjs"], default="auto")
    render.add_argument("--browser")
    render.add_argument("--viewport-width", type=int, default=1440)
    render.add_argument("--viewport-height", type=int, default=1000)
    render.add_argument("--scale", type=int, default=2)
    render.add_argument("--analysis", help="架构图阶段化分析清单；架构图必需")
    render.add_argument("--facts", help="scan 生成的事实清单；架构图必需")
    render.add_argument("--approval", help="与 analysis/diagram 摘要匹配的用户确认凭据；架构图必需")
    render.add_argument("--review", help="与确认凭据绑定的结构审阅报告；架构图必需")
    render.add_argument("--source-root", help="可选源码根目录，用于复核证据路径和行号")
    render.add_argument("--reuse-layout-cache", action="store_true", help="复用内容、版本和源码证据均匹配的布局/审阅结果")
    render.set_defaults(func=_cmd_render)
    capture = sub.add_parser("capture", help="打开本地 HTML 并截图")
    capture.add_argument("html")
    capture.add_argument("--png", required=True)
    capture.add_argument("--report")
    capture.add_argument("--browser")
    capture.add_argument("--viewport-width", type=int, default=1440)
    capture.add_argument("--viewport-height", type=int, default=1000)
    capture.add_argument("--scale", type=int, default=2)
    capture.add_argument("--analysis")
    capture.add_argument("--diagram")
    capture.add_argument("--facts")
    capture.add_argument("--review")
    capture.add_argument("--approval")
    capture.add_argument("--source-root")
    capture.add_argument("--reuse-layout-cache", action="store_true", help="复用内容、版本和源码证据均匹配的审阅结果")
    capture.set_defaults(func=_cmd_capture)
    loop = sub.add_parser("review-loop", help="生成截图和视觉审查请求；由 Skill 提供图像评估")
    loop.add_argument("diagram")
    loop.add_argument("-o", "--output-dir", required=True)
    loop.add_argument("--max-rounds", type=int, default=4)
    loop.add_argument("--browser")
    loop.add_argument("--analysis")
    loop.add_argument("--facts")
    loop.add_argument("--approval")
    loop.add_argument("--review")
    loop.add_argument("--source-root")
    loop.add_argument("--layout-backend", choices=["auto", "builtin", "elkjs"], default="builtin")
    loop.add_argument("--reuse-layout-cache", action="store_true", help="复用内容、版本和源码证据均匹配的审阅结果")
    loop.set_defaults(func=_cmd_review_loop)
    apply = sub.add_parser("apply-review", help="应用结构化视觉审查修正")
    apply.add_argument("diagram")
    apply.add_argument("--review", required=True)
    apply.add_argument("-o", "--output", required=True)
    apply.set_defaults(func=_cmd_apply_review)
    review_prompt = sub.add_parser("review-prompt", help="导出可供当前模型视觉复核的检查提示")
    review_prompt.add_argument("-o", "--output", required=True)
    review_prompt.set_defaults(func=_cmd_review_prompt)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
