"""阶段化架构分析产物的结构与连通性审计。

本模块只检查分析清单是否自洽、证据引用是否可定位、关系是否进入图以及声明的主路径是否连通。
它不能证明分析者穷尽了源码中的全部动态行为；该部分必须由 Skill 的逐模块源码复核完成。
"""

from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
from typing import Any


_LAYER_ROLES = {"access", "orchestration", "capability", "business", "data_external", "governance", "other", "unclassified"}
_RELATION_KINDS = {
    "function_call", "http", "message", "event", "dependency_injection", "configuration",
    "data_read", "data_write", "file_read", "file_write", "external_call", "model_call",
    "process_spawn", "retry", "governance", "import", "other",
}
_CANDIDATE_DECISIONS = {"included", "merged", "excluded"}
_TERMINAL_TYPES = {"response", "persisted", "completed", "handoff"}
_DENSITY_SIGNALS = {
    "composite_actions", "state_and_control", "dispatch_and_execution",
    "multiple_technical_boundaries", "separate_data_purposes", "independent_lifecycle",
    "independent_relationships",
}


def _is_nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _collect_diagrams(diagram: Any, errors: list[str]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}

    def visit(item: Any, where: str) -> None:
        if not isinstance(item, dict):
            errors.append(f"{where} 必须是 JSON 对象")
            return
        diagram_id = item.get("id")
        if not _is_nonempty_text(diagram_id):
            errors.append(f"{where}.id 必须是非空文本")
            return
        if diagram_id in found:
            errors.append(f"图 ID 重复：{diagram_id}")
            return
        found[diagram_id] = item
        children = item.get("subDiagrams", [])
        if not isinstance(children, list):
            errors.append(f"{where}.subDiagrams 必须是数组")
            return
        for index, child in enumerate(children):
            visit(child, f"{where}.subDiagrams[{index}]")

    visit(diagram, "diagram")
    return found


def _check_evidence(
    references: Any,
    where: str,
    errors: list[str],
    warnings: list[str],
    source_root: Path | None,
) -> None:
    if not isinstance(references, list) or not references:
        errors.append(f"{where} 必须至少包含一条源码证据")
        return
    for index, ref in enumerate(references):
        location = f"{where}[{index}]"
        if not isinstance(ref, dict) or not _is_nonempty_text(ref.get("path")):
            errors.append(f"{location} 缺少源码路径")
            continue
        line = ref.get("line")
        if not isinstance(line, int) or isinstance(line, bool) or line < 1:
            errors.append(f"{location}.line 必须是正整数")
            continue
        end_line = ref.get("endLine", line)
        if not isinstance(end_line, int) or isinstance(end_line, bool) or end_line < line:
            errors.append(f"{location}.endLine 必须不小于 line")
            continue
        if not _is_nonempty_text(ref.get("claim")):
            errors.append(f"{location}.claim 必须说明该证据支持的事实")
        if source_root is None:
            if not _is_nonempty_text(ref.get("url")):
                warnings.append(f"{location} 未提供可本地核验根目录或源码 URL；行号需人工复核")
            continue
        candidate = (source_root / ref["path"]).resolve()
        try:
            candidate.relative_to(source_root)
        except ValueError:
            errors.append(f"{location}.path 超出源码根目录")
            continue
        if not candidate.is_file():
            errors.append(f"{location}.path 不存在：{ref['path']}")
            continue
        try:
            line_count = len(candidate.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError as exc:
            errors.append(f"{location}.path 无法读取：{exc}")
            continue
        if end_line > line_count:
            errors.append(f"{location} 行号超出文件范围（文件共 {line_count} 行）")


def _check_density_review(
    stage_b: dict[str, Any],
    module_by_id: dict[str, dict[str, Any]],
    candidate_by_id: dict[str, dict[str, Any]],
    disposition_by_candidate: dict[str, dict[str, Any]],
    main_diagram: Any,
    errors: list[str],
    warnings: list[str],
    source_root: Path | None,
) -> tuple[list[dict[str, Any]], int, int]:
    """核对主图每层数量、单模块二次拆分例外及逐模块拆分信号复核。"""
    density = stage_b.get("densityReview")
    if not isinstance(density, dict):
        errors.append("stageB.densityReview 缺失；必须记录主图逐层密度和逐模块拆分复核")
        return [], 0, 0
    if density.get("targetModulesPerLayer") != {"min": 3, "max": 5}:
        errors.append("stageB.densityReview.targetModulesPerLayer 必须记录软目标 3 至 5 个模块")

    if not isinstance(main_diagram, dict):
        errors.append("主图必须是对象，才能核对各层实际模块数量")
        return [], 0, 0
    diagram_layers = main_diagram.get("layers", [])
    diagram_nodes = main_diagram.get("nodes", [])
    if not isinstance(diagram_layers, list) or not isinstance(diagram_nodes, list):
        errors.append("主图 layers 和 nodes 必须是数组，才能核对密度")
        return [], 0, 0

    stage_layers = stage_b.get("layers", [])
    stage_layer_by_id = {
        item.get("id"): item for item in stage_layers
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    } if isinstance(stage_layers, list) else {}
    nodes_by_layer: dict[str, list[str]] = defaultdict(list)
    for index, node in enumerate(diagram_nodes):
        if not isinstance(node, dict) or not isinstance(node.get("id"), str):
            errors.append(f"diagram.nodes[{index}] 缺少有效 ID，无法计入层密度")
            continue
        node_id = node["id"]
        module = module_by_id.get(node_id)
        if module is None:
            errors.append(f"主图节点 {node_id} 未映射到阶段 B 的源码模块")
        elif node.get("layer") != module.get("layerId"):
            errors.append(f"主图节点 {node_id} 的层与阶段 B 模块归层不一致")
        layer_id = node.get("layer")
        if not isinstance(layer_id, str):
            errors.append(f"主图节点 {node_id} 缺少 layer，无法计入层密度")
            continue
        nodes_by_layer[layer_id].append(node_id)

    reviews = density.get("layerReviews")
    if not isinstance(reviews, list):
        errors.append("stageB.densityReview.layerReviews 必须逐主图层记录密度检查")
        reviews = []
    review_by_layer: dict[str, dict[str, Any]] = {}
    density_report: list[dict[str, Any]] = []
    singleton_exceptions = 0
    main_layer_ids = {
        item.get("id") for item in diagram_layers
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if len(main_layer_ids) != len(diagram_layers):
        errors.append("主图层 ID 缺失或重复")
    for index, item in enumerate(reviews):
        where = f"stageB.densityReview.layerReviews[{index}]"
        if not isinstance(item, dict) or not isinstance(item.get("layerId"), str):
            errors.append(f"{where}.layerId 无效")
            continue
        layer_id = item["layerId"]
        if layer_id in review_by_layer:
            errors.append(f"主图层重复进行密度复核：{layer_id}")
        review_by_layer[layer_id] = item
        if layer_id not in main_layer_ids:
            errors.append(f"{where}.layerId 未指向主图实际层")
        if layer_id not in stage_layer_by_id:
            errors.append(f"{where}.layerId 未在阶段 B 分层清单中定义")
        final_ids = item.get("finalModuleIds")
        declared = list(final_ids) if isinstance(final_ids, list) and all(isinstance(value, str) for value in final_ids) else []
        actual = nodes_by_layer.get(layer_id, [])
        if len(declared) != len(set(declared)) or set(declared) != set(actual):
            errors.append(f"{where}.finalModuleIds 必须与主图该层节点完全一致")
        if not isinstance(final_ids, list):
            errors.append(f"{where}.finalModuleIds 必须是数组")
        if any(module_id not in module_by_id for module_id in declared):
            errors.append(f"{where}.finalModuleIds 包含未知阶段 B 模块")

        layer = stage_layer_by_id.get(layer_id, {})
        role = layer.get("role")
        count = len(actual)
        triggered = item.get("secondPassTriggered")
        action = item.get("secondPassAction")
        outcome = item.get("outcome")
        reason = item.get("reason")
        source_candidates = item.get("sourceCandidateIds")
        evidence = item.get("evidence")
        _check_evidence(evidence, f"{where}.evidence", errors, warnings, source_root)
        if not _is_nonempty_text(reason):
            errors.append(f"{where}.reason 必须记录密度检查结论")
        if not isinstance(source_candidates, list) or any(candidate_id not in candidate_by_id for candidate_id in source_candidates):
            errors.append(f"{where}.sourceCandidateIds 必须引用已盘点候选")
            source_candidates = []

        if count == 0:
            errors.append(f"主图层 {layer_id} 没有模块；空层应移除并记录到 absentRoles")
        if role == "governance":
            if outcome != "governance_exempt" or triggered is not False or action != "not_needed":
                errors.append(f"{where} 治理横切层必须标为 governance_exempt，且不触发二次拆分")
        elif count < 3:
            singleton_exceptions += 1
            warnings.append(f"主图层 {layer_id} 只有 {count} 个模块，低于 3 至 5 个软目标")
            if outcome != "below_target_reviewed" or triggered is not True or action not in {"split", "retain_after_review"}:
                errors.append(f"{where} 低于软目标时必须记录二次拆分复核及结论")
            resulting_candidates = {
                candidate_id for candidate_id, disposition in disposition_by_candidate.items()
                if disposition.get("moduleId") in set(actual) and disposition.get("decision") in {"included", "merged"}
            }
            if not source_candidates or set(source_candidates) != resulting_candidates:
                errors.append(f"{where}.sourceCandidateIds 必须列出该层全部实际来源候选")
        elif count <= 5:
            if outcome != "in_target":
                errors.append(f"{where} 3 至 5 个模块的层必须标为 in_target")
            if triggered is True and action != "split":
                errors.append(f"{where} 已执行二次拆分时 secondPassAction 必须为 split")
            if triggered is False and (action != "not_needed" or source_candidates):
                errors.append(f"{where} 未执行二次拆分时应使用 not_needed 且不列来源候选")
        else:
            warnings.append(f"主图层 {layer_id} 有 {count} 个模块，高于 3 至 5 个软目标；建议按真实职责分组或下钻")
            if outcome != "above_target_reviewed":
                errors.append(f"{where} 超过 5 个模块时必须记录分组/下钻审阅结论")
        density_report.append({
            "layerId": layer_id,
            "moduleCount": count,
            "target": None if role == "governance" else {"min": 3, "max": 5},
            "withinTarget": role == "governance" or 3 <= count <= 5,
            "outcome": outcome,
            "secondPassTriggered": triggered,
        })

    for layer_id in main_layer_ids - review_by_layer.keys():
        errors.append(f"主图层缺少密度复核：{layer_id}")

    decomposition_reviews = density.get("moduleDecompositionReviews")
    if not isinstance(decomposition_reviews, list):
        errors.append("stageB.densityReview.moduleDecompositionReviews 必须逐主图模块检查拆分信号")
        decomposition_reviews = []
    decomposition_by_module: dict[str, dict[str, Any]] = {}
    main_module_ids = {node_id for node_ids in nodes_by_layer.values() for node_id in node_ids}
    for index, item in enumerate(decomposition_reviews):
        where = f"stageB.densityReview.moduleDecompositionReviews[{index}]"
        if not isinstance(item, dict) or item.get("moduleId") not in main_module_ids:
            errors.append(f"{where}.moduleId 未指向主图模块")
            continue
        module_id = item["moduleId"]
        if module_id in decomposition_by_module:
            errors.append(f"模块重复进行拆分信号复核：{module_id}")
        decomposition_by_module[module_id] = item
        checked = item.get("signalsChecked")
        found = item.get("signalsFound")
        checked_set = set(checked) if isinstance(checked, list) and all(isinstance(value, str) for value in checked) else set()
        found_set = set(found) if isinstance(found, list) and all(isinstance(value, str) for value in found) else set()
        if checked_set != _DENSITY_SIGNALS:
            errors.append(f"{where}.signalsChecked 必须覆盖全部 7 类通用拆分信号")
        if not found_set <= _DENSITY_SIGNALS or not found_set <= checked_set:
            errors.append(f"{where}.signalsFound 必须是已检查拆分信号的子集")
        if item.get("decision") != "retain":
            errors.append(f"{where} 仍有未完成的进一步拆分；必须返回阶段 B")
        if not _is_nonempty_text(item.get("reason")):
            errors.append(f"{where}.reason 必须说明保留该模块的职责依据")
        _check_evidence(item.get("evidence"), f"{where}.evidence", errors, warnings, source_root)
    for module_id in main_module_ids - decomposition_by_module.keys():
        errors.append(f"主图模块缺少拆分信号复核：{module_id}")

    return density_report, len(decomposition_by_module), singleton_exceptions


def audit_analysis(
    analysis: Any,
    diagram: Any,
    *,
    source_root: str | Path | None = None,
) -> dict[str, Any]:
    """检查 A-D 阶段产物、图边映射和主路径连通性并返回报告。"""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(analysis, dict):
        return {"passed": False, "errors": ["analysis 必须是 JSON 对象"], "warnings": []}

    root = Path(source_root).resolve() if source_root is not None else None
    if root is not None and not root.is_dir():
        errors.append(f"源码根目录不存在或不是目录：{root}")
        root = None

    for stage in ("stageA", "stageB", "stageC", "stageD"):
        record = analysis.get(stage)
        if not isinstance(record, dict):
            errors.append(f"缺少 {stage} 阶段产物")
        elif record.get("status") != "complete":
            errors.append(f"{stage} 尚未标记為 complete")

    coverage = analysis.get("coverage")
    if not isinstance(coverage, dict):
        errors.append("analysis.coverage 缺失；必须如实列出已分析与未分析范围")
    else:
        for field in ("analyzed", "notAnalyzed"):
            records = coverage.get(field)
            if not isinstance(records, list):
                errors.append(f"analysis.coverage.{field} 必须是数组")
                continue
            for index, item in enumerate(records):
                if not isinstance(item, dict) or not _is_nonempty_text(item.get("scope")):
                    errors.append(f"analysis.coverage.{field}[{index}].scope 必须说明覆盖范围")
                if field == "analyzed" and (not isinstance(item.get("fileCount"), int) or item["fileCount"] < 0):
                    errors.append(f"analysis.coverage.analyzed[{index}].fileCount 必须是非负整数")
                if field == "notAnalyzed" and not _is_nonempty_text(item.get("reason")):
                    errors.append(f"analysis.coverage.notAnalyzed[{index}].reason 必须说明未分析原因")

    stage_a = analysis.get("stageA", {}) if isinstance(analysis.get("stageA"), dict) else {}
    stage_b = analysis.get("stageB", {}) if isinstance(analysis.get("stageB"), dict) else {}
    stage_c = analysis.get("stageC", {}) if isinstance(analysis.get("stageC"), dict) else {}
    stage_d = analysis.get("stageD", {}) if isinstance(analysis.get("stageD"), dict) else {}

    candidates = stage_a.get("candidates")
    candidate_by_id: dict[str, dict[str, Any]] = {}
    if not isinstance(candidates, list) or not candidates:
        errors.append("stageA.candidates 必须是非空数组")
        candidates = []
    for index, candidate in enumerate(candidates):
        where = f"stageA.candidates[{index}]"
        if not isinstance(candidate, dict) or not _is_nonempty_text(candidate.get("id")):
            errors.append(f"{where}.id 无效")
            continue
        candidate_id = candidate["id"]
        if candidate_id in candidate_by_id:
            errors.append(f"候选 ID 重复：{candidate_id}")
        candidate_by_id[candidate_id] = candidate
        if not _is_nonempty_text(candidate.get("kind")) or not _is_nonempty_text(candidate.get("title")):
            errors.append(f"{where} 必须包含 kind 和 title")
        _check_evidence(candidate.get("evidence"), f"{where}.evidence", errors, warnings, root)

    layers = stage_b.get("layers")
    modules = stage_b.get("modules")
    dispositions = stage_b.get("candidateDisposition")
    layer_ids: set[str] = set()
    if not isinstance(layers, list):
        errors.append("stageB.layers 必须是数组；允许某些职责层缺席，但不得省略分层盘点")
        layers = []
    for index, layer in enumerate(layers):
        where = f"stageB.layers[{index}]"
        if not isinstance(layer, dict) or not _is_nonempty_text(layer.get("id")):
            errors.append(f"{where}.id 无效")
            continue
        if layer["id"] in layer_ids:
            errors.append(f"层 ID 重复：{layer['id']}")
        layer_ids.add(layer["id"])
        if layer.get("role") not in _LAYER_ROLES:
            errors.append(f"{where}.role 必须是通用职责角色之一；不适用的层可不创建")
        if not _is_nonempty_text(layer.get("name")) or not _is_nonempty_text(layer.get("reason")):
            errors.append(f"{where} 必须包含 name 和分层依据 reason")

    module_by_id: dict[str, dict[str, Any]] = {}
    if not isinstance(modules, list) or not modules:
        errors.append("stageB.modules 必须是非空数组")
        modules = []
    for index, module in enumerate(modules):
        where = f"stageB.modules[{index}]"
        if not isinstance(module, dict) or not _is_nonempty_text(module.get("id")):
            errors.append(f"{where}.id 无效")
            continue
        module_id = module["id"]
        if module_id in module_by_id:
            errors.append(f"模块 ID 重复：{module_id}")
        module_by_id[module_id] = module
        if module.get("layerId") not in layer_ids:
            errors.append(f"{where}.layerId 未指向已定义层")
        for field in ("title", "responsibility"):
            if not _is_nonempty_text(module.get(field)):
                errors.append(f"{where}.{field} 必须是非空文本")
        _check_evidence(module.get("evidence"), f"{where}.evidence", errors, warnings, root)

    if not isinstance(dispositions, list):
        errors.append("stageB.candidateDisposition 必须是数组")
        dispositions = []
    disposition_by_candidate: dict[str, dict[str, Any]] = {}
    modules_backed: set[str] = set()
    for index, item in enumerate(dispositions):
        where = f"stageB.candidateDisposition[{index}]"
        if not isinstance(item, dict) or item.get("candidateId") not in candidate_by_id:
            errors.append(f"{where}.candidateId 未指向已盘点候选")
            continue
        candidate_id = item["candidateId"]
        if candidate_id in disposition_by_candidate:
            errors.append(f"候选被重复归并或处置：{candidate_id}")
        disposition_by_candidate[candidate_id] = item
        if item.get("decision") not in _CANDIDATE_DECISIONS:
            errors.append(f"{where}.decision 必须为 included、merged 或 excluded")
            continue
        if item.get("layerId") not in layer_ids:
            errors.append(f"{where}.layerId 未指向已定义层；未归类项请使用 unclassified 层")
        module_id = item.get("moduleId")
        if item["decision"] in {"included", "merged"}:
            if module_id not in module_by_id:
                errors.append(f"{where} 的 moduleId 未指向最终模块")
            else:
                modules_backed.add(module_id)
                if module_by_id[module_id].get("layerId") != item.get("layerId"):
                    errors.append(f"{where}.layerId 与最终模块 {module_id} 的归层不一致")
        elif not _is_nonempty_text(item.get("reason")):
            errors.append(f"{where} 被排除时必须给出 reason")
    for candidate_id in candidate_by_id.keys() - disposition_by_candidate.keys():
        errors.append(f"候选没有分层/归并/排除结论：{candidate_id}")
    for module_id in module_by_id.keys() - modules_backed:
        errors.append(f"最终模块没有任何候选来源：{module_id}")

    relations = stage_c.get("relations")
    relation_by_id: dict[str, dict[str, Any]] = {}
    if not isinstance(relations, list):
        errors.append("stageC.relations 必须是数组")
        relations = []
    for index, relation in enumerate(relations):
        where = f"stageC.relations[{index}]"
        if not isinstance(relation, dict) or not _is_nonempty_text(relation.get("id")):
            errors.append(f"{where}.id 无效")
            continue
        relation_id = relation["id"]
        if relation_id in relation_by_id:
            errors.append(f"关系 ID 重复：{relation_id}")
        relation_by_id[relation_id] = relation
        if relation.get("from") not in module_by_id or relation.get("to") not in module_by_id:
            errors.append(f"{where} 起点或终点未指向最终模块")
        if relation.get("kind") not in _RELATION_KINDS:
            errors.append(f"{where}.kind 不是支持的关系类型")
        if not _is_nonempty_text(relation.get("label")):
            errors.append(f"{where}.label 必须说明关系语义")
        _check_evidence(relation.get("evidence"), f"{where}.evidence", errors, warnings, root)

    review = stage_d.get("coverageReview")
    module_reviews = review.get("moduleReviews") if isinstance(review, dict) else None
    if not isinstance(module_reviews, list):
        errors.append("stageD.coverageReview.moduleReviews 必须逐模块记录入边、出边、副作用与分支复核")
        module_reviews = []
    module_review_by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(module_reviews):
        where = f"stageD.coverageReview.moduleReviews[{index}]"
        if not isinstance(item, dict) or item.get("moduleId") not in module_by_id:
            errors.append(f"{where}.moduleId 未指向最终模块")
            continue
        module_id = item["moduleId"]
        if module_id in module_review_by_id:
            errors.append(f"模块重复进行覆盖复核：{module_id}")
        module_review_by_id[module_id] = item
        expected_incoming = {rel_id for rel_id, rel in relation_by_id.items() if rel.get("to") == module_id}
        expected_outgoing = {rel_id for rel_id, rel in relation_by_id.items() if rel.get("from") == module_id}
        for field, expected in (("incomingRelationIds", expected_incoming), ("outgoingRelationIds", expected_outgoing)):
            declared = item.get(field)
            declared_ids = {value for value in declared if isinstance(value, str)} if isinstance(declared, list) else set()
            if not isinstance(declared, list) or len(declared_ids) != len(declared) or declared_ids != expected:
                missing = sorted(expected - declared_ids)
                extra = sorted(declared_ids - expected)
                errors.append(f"{where}.{field} 与阶段 C 不一致（缺少：{missing}；多出：{extra}）")
        side_effects = item.get("sideEffectRelationIds")
        if not isinstance(side_effects, list):
            errors.append(f"{where}.sideEffectRelationIds 必须为数组")
        else:
            side_effect_ids = {value for value in side_effects if isinstance(value, str)}
            if len(side_effect_ids) != len(side_effects) or not side_effect_ids <= expected_outgoing:
                errors.append(f"{where}.sideEffectRelationIds 必须是无重复的该模块已提取出边子集")
        if item.get("branchesReviewed") is not True:
            errors.append(f"{where}.branchesReviewed 必须为 true")
        if not isinstance(item.get("unmodeledActions"), list) or item.get("unmodeledActions"):
            errors.append(f"{where}.unmodeledActions 必须为空；未建模动作应先回到阶段 C")
    for module_id in module_by_id.keys() - module_review_by_id.keys():
        errors.append(f"模块缺少逐模块关系覆盖复核：{module_id}")

    diagram_index = _collect_diagrams(diagram, errors)
    if isinstance(diagram, dict) and diagram.get("type") == "architecture":
        density_report, density_reviewed_modules, singleton_exceptions = _check_density_review(
            stage_b,
            module_by_id,
            candidate_by_id,
            disposition_by_candidate,
            diagram,
            errors,
            warnings,
            root,
        )
    else:
        density_report, density_reviewed_modules, singleton_exceptions = [], 0, 0
    if isinstance(diagram, dict) and diagram.get("type") == "architecture":
        root_nodes = diagram.get("nodes", []) if isinstance(diagram.get("nodes"), list) else []
        root_edges = diagram.get("edges", []) if isinstance(diagram.get("edges"), list) else []
        root_count = len(root_nodes)
        if root_count < 12:
            exception = stage_b.get("densityReview", {}).get("mainGraphException") if isinstance(stage_b.get("densityReview"), dict) else None
            if not isinstance(exception, dict) or not _is_nonempty_text(exception.get("reason")):
                errors.append("主图少于 12 个模块，必须以源码证据说明无法再拆分的例外原因")
            else:
                _check_evidence(exception.get("evidence"), "stageB.densityReview.mainGraphException.evidence", errors, warnings, root)
                warnings.append(f"主图仅 {root_count} 个模块；已记录证据不足例外：{exception['reason']}")
        if root_count > 25:
            errors.append(f"主图有 {root_count} 个模块，超过 25 个硬上限；应拆分图面，不得合并职责")
        if len(root_edges) > 8:
            errors.append(f"主图有 {len(root_edges)} 条连线，超过 8 条硬上限")
        if diagram.get("showEdgeLabels") is not False:
            errors.append("主图 showEdgeLabels 必须为 false")
        root_node_by_id = {node.get("id"): node for node in root_nodes if isinstance(node, dict)}
        for index, node in enumerate(root_nodes):
            if not isinstance(node, dict):
                continue
            desc = "".join(str(node.get("desc", "")).split())
            if len(desc) > 12 or "…" in desc or "..." in desc:
                errors.append(f"主图节点 {node.get('id')} 的说明超过 12 字或含省略号")
            _check_evidence(node.get("evidence"), f"diagram.nodes[{index}].evidence", errors, warnings, root)
        for index, edge in enumerate(root_edges):
            if not isinstance(edge, dict):
                continue
            source = root_node_by_id.get(edge.get("from"))
            target = root_node_by_id.get(edge.get("to"))
            if not source or not target or source.get("layer") == target.get("layer"):
                errors.append(f"主图连线 {edge.get('id')} 不是层间主流向")
            if edge.get("main") is not True:
                errors.append(f"主图连线 {edge.get('id')} 必须表示主流向并标记 main=true")
            if str(edge.get("label", "")).strip():
                errors.append(f"主图连线 {edge.get('id')} 不得显示标签；语义应放入下钻图")
            _check_evidence(edge.get("evidence"), f"diagram.edges[{index}].evidence", errors, warnings, root)

        for diagram_id, graph in diagram_index.items():
            if graph is diagram:
                continue
            for index, node in enumerate(graph.get("nodes", []) if isinstance(graph.get("nodes"), list) else []):
                if isinstance(node, dict):
                    _check_evidence(node.get("evidence"),
                                    f"diagram[{diagram_id}].nodes[{index}].evidence", errors, warnings, root)
            for index, edge in enumerate(graph.get("edges", []) if isinstance(graph.get("edges"), list) else []):
                if isinstance(edge, dict):
                    _check_evidence(edge.get("evidence"),
                                    f"diagram[{diagram_id}].edges[{index}].evidence", errors, warnings, root)

        for diagram_id, graph in diagram_index.items():
            if graph is diagram:
                continue
            graph_edges = graph.get("edges", [])
            graph_nodes = graph.get("nodes", [])
            if graph.get("type") != "sequence" and len(graph_edges) > 8:
                errors.append(f"下钻图 {diagram_id} 有 {len(graph_edges)} 条边，超过 8 条硬上限；必须拆分")
            if not 3 <= len(graph_nodes) <= 8:
                warnings.append(f"下钻图 {diagram_id} 有 {len(graph_nodes)} 个节点，建议控制在 3 至 8 个")
            if graph.get("type") == "sequence" and len(graph_edges) > 12:
                warnings.append(f"时序图 {diagram_id} 有 {len(graph_edges)} 条消息，超过 12 条软目标；建议拆分")
    mapped_relations: set[str] = set()
    diagram_edges = 0
    for diagram_id, item in diagram_index.items():
        nodes = {node.get("id"): node for node in item.get("nodes", []) if isinstance(node, dict)}
        edges = item.get("edges", [])
        if not isinstance(edges, list):
            errors.append(f"图 {diagram_id} 的 edges 必须是数组")
            continue
        for index, edge in enumerate(edges):
            diagram_edges += 1
            where = f"diagram[{diagram_id}].edges[{index}]"
            if not isinstance(edge, dict):
                errors.append(f"{where} 必须是对象")
                continue
            refs = edge.get("relationIds")
            if not isinstance(refs, list) or not refs:
                errors.append(f"{where} 缺少 relationIds；图边必须能追溯到阶段 C 关系")
                continue
            for relation_id in refs:
                relation = relation_by_id.get(relation_id)
                if relation is None:
                    errors.append(f"{where} 引用了未知关系 {relation_id}")
                    continue
                if edge.get("from") != relation.get("from") or edge.get("to") != relation.get("to"):
                    errors.append(f"{where} 的端点与关系 {relation_id} 的方向不一致")
                if edge.get("from") not in nodes or edge.get("to") not in nodes:
                    errors.append(f"{where} 的端点未出现在该图节点中")
                mapped_relations.add(relation_id)
    for relation_id in relation_by_id.keys() - mapped_relations:
        errors.append(f"阶段 C 关系未进入任何主图/子图：{relation_id}")

    paths = stage_d.get("paths")
    if not isinstance(paths, list) or not paths:
        errors.append("stageD.paths 必须至少有一条入口到响应/持久化/完成端点的成功路径")
        paths = []
    adjacency: dict[str, set[str]] = defaultdict(set)
    for relation in relation_by_id.values():
        if relation.get("from") in module_by_id and relation.get("to") in module_by_id:
            adjacency[relation["from"]].add(relation["to"])
            if relation.get("kind") == "governance":
                # Governance is a cross-cutting constraint, not a payload-flow direction.
                adjacency[relation["to"]].add(relation["from"])
    path_counts: list[dict[str, Any]] = []
    reachable_from_entries: set[str] = set()
    for index, path in enumerate(paths):
        where = f"stageD.paths[{index}]"
        if not isinstance(path, dict):
            errors.append(f"{where} 必须是对象")
            continue
        nodes = path.get("nodeIds")
        edge_ids = path.get("relationIds")
        if not isinstance(nodes, list) or len(nodes) < 2 or not isinstance(edge_ids, list):
            errors.append(f"{where} 必须包含 nodeIds 和 relationIds")
            continue
        if len(edge_ids) != len(nodes) - 1:
            errors.append(f"{where} 的关系数必须等于节点数减一")
        if nodes[0] != path.get("entry") or nodes[-1] != path.get("terminal"):
            errors.append(f"{where} 的入口/终点必须与 nodeIds 首尾一致")
        if path.get("terminalType") not in _TERMINAL_TYPES:
            errors.append(f"{where}.terminalType 必须是 response、persisted、completed 或 handoff")
        if path.get("status") != "complete":
            errors.append(f"{where} 未标记为 complete")
        for node_id in nodes:
            if node_id not in module_by_id:
                errors.append(f"{where} 引用了未知模块 {node_id}")
        for edge_index, relation_id in enumerate(edge_ids):
            relation = relation_by_id.get(relation_id)
            if relation is None:
                errors.append(f"{where} 引用了未知关系 {relation_id}")
                continue
            if edge_index + 1 < len(nodes) and (
                relation.get("from") != nodes[edge_index] or relation.get("to") != nodes[edge_index + 1]
            ):
                errors.append(f"{where} 的关系 {relation_id} 与相邻节点顺序不匹配")
        if nodes and nodes[0] in module_by_id:
            reachable = {nodes[0]}
            queue = deque([nodes[0]])
            while queue:
                current = queue.popleft()
                for target in adjacency[current] - reachable:
                    reachable.add(target)
                    queue.append(target)
            reachable_from_entries.update(reachable)
            if nodes[-1] not in reachable:
                errors.append(f"{where} 从入口无法沿阶段 C 关系到达终点")
        path_counts.append({"id": path.get("id"), "nodes": len(nodes), "relations": len(edge_ids)})

    unreachable_modules = sorted(module_by_id.keys() - reachable_from_entries)
    if unreachable_modules:
        errors.append("从已声明主路径入口无法到达这些模块：" + "、".join(unreachable_modules))

    if not isinstance(review, dict):
        errors.append("stageD.coverageReview 缺失")
    else:
        for check in ("candidateInventoryReviewed", "moduleIngressEgressReviewed", "sideEffectsReviewed", "dispatchAndReturnReviewed"):
            if review.get(check) is not True:
                errors.append(f"stageD.coverageReview.{check} 必须为 true")
        if not isinstance(review.get("iterations"), int) or review.get("iterations", 0) < 1:
            errors.append("stageD.coverageReview.iterations 必须记录至少一轮校验")
        backfilled = review.get("backfilledRelationIds", [])
        if not isinstance(backfilled, list) or any(item not in relation_by_id for item in backfilled):
            errors.append("stageD.coverageReview.backfilledRelationIds 必须引用已补入的阶段 C 关系")

    return {
        "passed": not errors,
        "counts": {
            "candidates": len(candidate_by_id),
            "layers": len(layer_ids),
            "modules": len(module_by_id),
            "reviewedModules": len(module_review_by_id),
            "densityReviewedModules": density_reviewed_modules,
            "singletonLayerExceptions": singleton_exceptions,
            "relations": len(relation_by_id),
            "diagramEdges": diagram_edges,
            "mainGraphModules": len(diagram.get("nodes", [])) if isinstance(diagram, dict) and isinstance(diagram.get("nodes"), list) else 0,
            "mainGraphEdges": len(diagram.get("edges", [])) if isinstance(diagram, dict) and isinstance(diagram.get("edges"), list) else 0,
            "mainPaths": len(path_counts),
            "reachableModules": len(reachable_from_entries),
            "unreachableModules": unreachable_modules,
        },
        "layerDensity": density_report,
        "pathChecks": path_counts,
        "errors": errors,
        "warnings": sorted(set(warnings)),
        "limits": [
            "本审计能检查候选处置、证据格式、关系到图边映射和已声明主路径的有向连通性。",
            "逐模块复核清单能发现关系清单与模块入/出边记录之间的不一致，但记录仍需由分析者回读源码确认。",
            "层密度审计能核对主图节点数量与声明的二次拆分记录；拆分信号的语义判断仍依赖源码复核，不能由字段结构单独证明。",
            "它不能证明候选或关系已穷尽源码；必须依照 Skill 对入口、分支、模块出入边和副作用逐项人工回源码复核。",
            "没有提供 source_root 时，源码行号和远程链接不做本地存在性检查。",
        ],
    }
