"""Deterministically render the human-readable analysis indexes from analysis.json."""

from __future__ import annotations

from typing import Any


_ROLE_NAMES = {
    "access": "接入", "orchestration": "编排", "capability": "能力",
    "business": "业务服务", "data_external": "数据与外部依赖",
    "governance": "治理", "other": "其他", "unclassified": "待归类",
}
_GENERATED = "<!-- 自动生成：请修改 analysis.json 后重新运行 analysis-reports。 -->"


def _list(value: Any) -> list[dict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _md(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")
    return text.replace("|", "\\|").strip()


def _evidence(items: Any) -> str:
    values = []
    for item in _list(items):
        location = _md(item.get("path", ""))
        if item.get("line") is not None:
            location += f":{_md(item['line'])}"
            if item.get("endLine") is not None:
                location += f"-{_md(item['endLine'])}"
        claim = _md(item.get("claim", ""))
        values.append(f"`{location}`" + (f"：{claim}" if claim else ""))
    return "<br>".join(values) or "—"


def _project(analysis: dict) -> str:
    return str(analysis.get("project", {}).get("name", "未命名项目"))


def _modules(analysis: dict) -> tuple[list[dict], list[dict], dict[str, str]]:
    stage_b = analysis.get("stageB", {})
    layers = _list(stage_b.get("layers", analysis.get("layers", [])))
    modules = _list(stage_b.get("modules", analysis.get("modules", [])))
    layer_names = {item.get("id"): item.get("name", item.get("id", "未命名层")) for item in layers}
    return layers, modules, layer_names


def render_modules(analysis: dict) -> str:
    layers, modules, layer_names = _modules(analysis)
    if not modules:
        raise ValueError("analysis.json 未包含 stageB.modules 或 modules")
    module_name = {item.get("id"): item.get("title", item.get("name", item.get("id", "未命名模块")))
                   for item in modules}
    stage_b = analysis.get("stageB", {})
    density = stage_b.get("densityReview", {}) if isinstance(stage_b, dict) else {}
    layer_reviews = {item.get("layerId"): item for item in _list(density.get("layerReviews", []))}
    decomposition = {item.get("moduleId"): item for item in _list(density.get("moduleDecompositionReviews", []))}
    dispositions = _list(stage_b.get("candidateDisposition", []))
    candidate_names = {item.get("id"): item.get("title", item.get("id"))
                       for item in _list(analysis.get("stageA", {}).get("candidates", []))}

    out = [f"# {_md(_project(analysis))} 模块清单", "", _GENERATED, ""]
    absent = _list(stage_b.get("absentRoles", []))
    if absent:
        out.extend(["## 未发现的职责层", ""])
        for item in absent:
            out.append(f"- **{_md(_ROLE_NAMES.get(item.get('role'), item.get('role', '未分类')))}**：{_md(item.get('reason', '未提供原因'))}")
        out.append("")

    ordered_layers = list(layers)
    known_layer_ids = {layer.get("id") for layer in ordered_layers}
    unassigned = [module for module in modules if module.get("layerId") not in known_layer_ids]
    if unassigned or not ordered_layers:
        ordered_layers.append({"id": "__unassigned__", "name": "未归类模块"})
    for layer in ordered_layers:
        layer_id = layer.get("id")
        name = layer.get("name", layer_id or "未分层")
        role = _ROLE_NAMES.get(layer.get("role"), layer.get("role"))
        if layer_id == "__unassigned__":
            layer_modules = unassigned
        elif not layers:
            layer_modules = modules
        else:
            layer_modules = [item for item in modules if item.get("layerId") == layer_id]
        review = layer_reviews.get(layer_id, {})
        suffix = f" / {_md(role)}" if role else ""
        out.extend([f"## {_md(name)}{suffix}（{len(layer_modules)} 个模块）", ""])
        out.extend(["| 模块 ID | 模块名称 | 职责 | 候选来源 | 证据 |",
                    "|---|---|---|---|---|"])
        for module in layer_modules:
            module_id = module.get("id", "")
            source_ids = [item.get("candidateId") for item in dispositions
                          if item.get("moduleId") == module_id]
            sources = "、".join(_md(candidate_names.get(item, item)) for item in source_ids) or "—"
            title = module.get("title", module.get("name", module_id))
            desc = module.get("responsibility", module.get("desc", module.get("summary", "")))
            out.append(f"| `{_md(module_id)}` | {_md(title)} | {_md(desc) or '—'} | {sources} | {_evidence(module.get('evidence'))} |")
        if not layer_modules:
            out.append("| — | — | 当前层未声明模块 | — | — |")
        if review:
            out.extend(["", f"**密度复核：** {_md(review.get('outcome', '未记录'))}；{_md(review.get('reason', '未提供说明'))}"])
        out.append("")

    out.extend(["## 拆分复核", ""])
    if decomposition:
        for module in modules:
            item = decomposition.get(module.get("id"))
            if item:
                out.append(f"- **{_md(module_name.get(module.get('id'), module.get('id')))}**：{_md(item.get('decision', '未记录'))}；{_md(item.get('reason', '未提供说明'))}")
    else:
        out.append("- analysis.json 未提供逐模块拆分复核记录。")
    out.append("")
    return "\n".join(out)


def render_relations(analysis: dict) -> str:
    relations = _list(analysis.get("stageC", {}).get("relations", analysis.get("relations", [])))
    _, modules, _ = _modules(analysis)
    names = {item.get("id"): item.get("title", item.get("name", item.get("id", "未命名模块")))
             for item in modules}
    out = [f"# {_md(_project(analysis))} 关系清单", "", _GENERATED, "",
           f"共 {len(relations)} 条已记录关系。", "",
           "| 关系 ID | 源模块 | 目标模块 | 类型 | 关系说明 | 条件 | 证据 |",
           "|---|---|---|---|---|---|---|"]
    for item in relations:
        source = item.get("from", "")
        target = item.get("to", "")
        out.append(f"| `{_md(item.get('id', ''))}` | {_md(names.get(source, source))} (`{_md(source)}`) | {_md(names.get(target, target))} (`{_md(target)}`) | {_md(item.get('kind', ''))} | {_md(item.get('label', ''))} | {_md(item.get('condition', '')) or '—'} | {_evidence(item.get('evidence'))} |")
    if not relations:
        out.append("| — | — | — | — | 未记录关系 | — | — |")
    return "\n".join(out) + "\n"


def render_main_paths(analysis: dict) -> str:
    stage_d = analysis.get("stageD", {})
    paths = _list(stage_d.get("paths", analysis.get("mainPaths", analysis.get("paths", []))))
    _, modules, _ = _modules(analysis)
    relations = _list(analysis.get("stageC", {}).get("relations", analysis.get("relations", [])))
    module_names = {item.get("id"): item.get("title", item.get("name", item.get("id", "未命名模块")))
                    for item in modules}
    relation_names = {item.get("id"): item.get("label", item.get("id", "未命名关系")) for item in relations}
    out = [f"# {_md(_project(analysis))} 主路径", "", _GENERATED, "",
           f"共 {len(paths)} 条已记录路径。", ""]
    for path in paths:
        path_id = path.get("id", "未命名路径")
        title = path.get("title", path_id)
        nodes = path.get("nodeIds", [])
        node_text = " → ".join(_md(module_names.get(node, node)) for node in nodes) or "未记录节点顺序"
        edge_ids = path.get("relationIds", [])
        edge_text = " → ".join(_md(relation_names.get(edge, edge)) for edge in edge_ids) or "未记录关系顺序"
        entry = path.get("entry", nodes[0] if nodes else "")
        terminal = path.get("terminal", nodes[-1] if nodes else "")
        out.extend([f"## {_md(title)} (`{_md(path_id)}`)", "",
                    f"- 入口：{_md(module_names.get(entry, entry))}",
                    f"- 终点：{_md(module_names.get(terminal, terminal))}（{_md(path.get('terminalType', '未记录类型'))}）",
                    f"- 状态：{_md(path.get('status', '未记录'))}",
                    f"- 节点顺序：{node_text}",
                    f"- 关系顺序：{edge_text}"])
        if path.get("notes"):
            out.append(f"- 备注：{_md(path['notes'])}")
        out.append("")

    review = stage_d.get("coverageReview", {}) if isinstance(stage_d, dict) else {}
    if review:
        out.extend(["## 主链路覆盖审计", "",
                    f"- 清点候选：{'通过' if review.get('candidateInventoryReviewed') else '未通过'}",
                    f"- 核对模块入边/出边：{'通过' if review.get('moduleIngressEgressReviewed') else '未通过'}",
                    f"- 复核副作用：{'通过' if review.get('sideEffectsReviewed') else '未通过'}",
                    f"- 复核调度与返回：{'通过' if review.get('dispatchAndReturnReviewed') else '未通过'}",
                    f"- 复核轮次：{_md(review.get('iterations', '未记录'))}",
                    f"- 补入关系：{'、'.join(map(_md, review.get('backfilledRelationIds', []))) or '无'}"])
        module_reviews = _list(review.get("moduleReviews", []))
        if module_reviews:
            out.extend(["", "| 模块 ID | 入边 | 出边 | 副作用边 | 分支复核 | 未建模动作 |",
                        "|---|---|---|---|---|---|"])
            for item in module_reviews:
                out.append(f"| `{_md(item.get('moduleId', ''))}` | {_md('、'.join(item.get('incomingRelationIds', []))) or '—'} | {_md('、'.join(item.get('outgoingRelationIds', []))) or '—'} | {_md('、'.join(item.get('sideEffectRelationIds', []))) or '—'} | {'是' if item.get('branchesReviewed') else '否'} | {_md('、'.join(item.get('unmodeledActions', []))) or '无'} |")
        out.append("")
    elif not paths:
        raise ValueError("analysis.json 未包含 stageD.paths 或 mainPaths")
    return "\n".join(out)


def generate_analysis_reports(analysis: dict) -> dict[str, str]:
    """Return stable Markdown reports derived only from the supplied analysis object."""
    return {
        "modules.md": render_modules(analysis),
        "relations.md": render_relations(analysis),
        "main-paths.md": render_main_paths(analysis),
    }
