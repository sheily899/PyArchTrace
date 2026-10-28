"""Build full or stage-scoped semantic work orders from the same rule source."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Any


_STAGE_NAMES = {"A": "stageA", "B": "stageB", "C": "stageC", "D": "stageD"}


def analysis_rules_path() -> Path:
    candidates = [
        Path(__file__).resolve().parents[2] / "references" / "analysis-stages.md",
        Path(sys.prefix) / "share" / "architecture-diagram" / "references" / "analysis-stages.md",
    ]
    return next((path for path in candidates if path.is_file()), candidates[0])


def _stage_rules(text: str, stage: str | None) -> str:
    if stage is None:
        return text.strip()
    heading = f"#### 阶段 {stage}："
    start = text.find(heading)
    if start < 0:
        raise ValueError(f"权威规则文件中未找到阶段 {stage}：{analysis_rules_path()}")
    next_heading = re.search(r"^#### 阶段 [A-D]：", text[start + len(heading):], re.MULTILINE)
    end = start + len(heading) + next_heading.start() if next_heading else len(text)
    return text[start:end].strip()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False)


def _refs(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            found.add(ref.rsplit("/", 1)[-1])
        for child in value.values():
            found.update(_refs(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_refs(child))
    return found


def _stage_schema(schema: dict, stage: str) -> dict:
    key = _STAGE_NAMES[stage]
    property_schema = schema.get("properties", {}).get(key)
    if not isinstance(property_schema, dict):
        raise ValueError(f"分析 schema 缺少 {key}")
    definitions = schema.get("$defs", {})
    needed: set[str] = set()
    pending = list(_refs(property_schema))
    while pending:
        name = pending.pop()
        if name in needed:
            continue
        needed.add(name)
        pending.extend(_refs(definitions.get(name, {})) - needed)
    return {
        "$schema": schema.get("$schema"),
        "title": f"{schema.get('title', '分析清单')} - 阶段 {stage}",
        "type": "object",
        "required": [key],
        "properties": {key: property_schema},
        "$defs": {name: definitions[name] for name in definitions if name in needed},
        "additionalProperties": False,
    }


def _evidence_paths(value: Any) -> set[str]:
    paths: set[str] = set()
    if isinstance(value, dict):
        evidence = value.get("evidence")
        if isinstance(evidence, list):
            paths.update(item["path"] for item in evidence
                         if isinstance(item, dict) and isinstance(item.get("path"), str))
        for child in value.values():
            paths.update(_evidence_paths(child))
    elif isinstance(value, list):
        for child in value:
            paths.update(_evidence_paths(child))
    return paths


def _fact_module_index(facts: dict) -> list[dict[str, str]]:
    return [{"path": item.get("path", ""), "module": item.get("module", "")}
            for item in facts.get("modules", []) if isinstance(item, dict)]


def _inventory_subset(facts: dict, *, include_directories: bool = False) -> dict:
    inventory = facts.get("inventory", {})
    keys = ["fileCount", "dependencyManifests", "configurationFiles", "containerFiles", "entryFiles"]
    if include_directories:
        keys.insert(0, "directories")
    selected = {key: inventory[key] for key in keys if key in inventory}
    sensitive = inventory.get("sensitivePaths")
    if isinstance(sensitive, list):
        selected["sensitivePathCount"] = len(sensitive)
    return selected


def _neighbor_paths(facts: dict, target_paths: set[str]) -> set[str]:
    modules = [item for item in facts.get("modules", []) if isinstance(item, dict)]
    by_path = {item.get("path"): item for item in modules if isinstance(item.get("path"), str)}
    selected = set(target_paths) & set(by_path)
    target_names = {by_path[path].get("module", "") for path in selected}
    target_names.discard("")
    imported_names: set[str] = set()
    for path in selected:
        for item in by_path[path].get("imports", []):
            if isinstance(item, dict) and isinstance(item.get("module"), str):
                imported_names.add(item["module"].lstrip("."))

    for path, item in by_path.items():
        name = item.get("module", "")
        if any(name == imported or name.startswith(imported + ".") or imported.startswith(name + ".")
               for imported in imported_names if imported):
            selected.add(path)
            continue
        for imported in item.get("imports", []):
            if not isinstance(imported, dict) or not isinstance(imported.get("module"), str):
                continue
            imported_name = imported["module"].lstrip(".")
            if any(imported_name == target or imported_name.startswith(target + ".")
                   or target.startswith(imported_name + ".") for target in target_names if target):
                selected.add(path)
                break
    return selected


def _selected_inputs(facts: dict, analysis: dict | None, stage: str,
                     module_id: str | None) -> tuple[dict, dict | None, list[str], list[str], list[str], list[str]]:
    facts_included: list[str] = ["project", "summary", "coverage"]
    facts_omitted: list[str] = []
    analysis_included: list[str] = []
    analysis_omitted: list[str] = []

    project_facts = {key: facts[key] for key in ("project", "summary", "coverage", "limitations") if key in facts}
    inventory = _inventory_subset(facts, include_directories=(stage == "A"))
    if inventory:
        project_facts["inventory"] = inventory
        facts_included.extend(f"inventory.{key}" for key in inventory)
    facts_omitted.extend(f"inventory.{key}" for key in facts.get("inventory", {}) if key not in inventory)

    module_index = _fact_module_index(facts)
    source_analysis: dict | None = None
    if stage == "A":
        project_facts["modules"] = facts.get("modules", [])
        project_facts["entrypoints"] = facts.get("entrypoints", [])
        facts_included.extend(["modules[*].path/module/imports/definitions/entrypoints", "entrypoints"])
        facts_omitted.append("无；保留候选提取需要的 Python AST 结构事实；非 Python 文件仅作路径盘点，不纳入语义抽象")
    elif stage == "B":
        assert analysis is not None
        candidates = analysis.get("stageA", {}).get("candidates", [])
        selected_paths = _evidence_paths(candidates)
        selected_modules = [item for item in facts.get("modules", [])
                            if isinstance(item, dict) and item.get("path") in selected_paths]
        project_facts["modules"] = selected_modules
        facts_included.append(f"modules[*] 候选证据路径匹配项（{len(selected_modules)} 个）")
        unmatched = sorted(selected_paths - {item.get("path") for item in selected_modules})
        if unmatched:
            facts_included.append(f"未匹配到 Python AST 索引的候选证据路径（不得据此形成非 Python 模块）：{', '.join(unmatched)}")
        facts_omitted.extend(["未被阶段 A 候选证据引用的 modules[*] AST 详情",
                              "与当前分层判定无关的 inventory 非必要字段"])
        source_analysis = {"project": analysis.get("project"), "coverage": analysis.get("coverage"),
                           "stageA": analysis.get("stageA")}
        analysis_included = ["project", "coverage", "stageA.candidates"]
        analysis_omitted = ["stageB", "stageC", "stageD（尚未生成或不属于阶段 B）"]
    elif stage == "C":
        assert analysis is not None and module_id is not None
        modules = analysis.get("stageB", {}).get("modules", [])
        target = next((item for item in modules if item.get("id") == module_id), None)
        if target is None:
            raise ValueError(f"analysis.json 的 stageB.modules 中找不到模块 ID：{module_id}")
        target_paths = _evidence_paths(target)
        full_paths = _neighbor_paths(facts, target_paths)
        full_modules = [item for item in facts.get("modules", [])
                        if isinstance(item, dict) and item.get("path") in full_paths]
        project_facts["moduleIndex"] = module_index
        project_facts["modules"] = full_modules
        facts_included.extend(["moduleIndex[*].path/module（定位全项目文件）",
                               f"modules[*] 目标模块及 AST 直接导入/导入方匹配项（{len(full_modules)} 个）"])
        facts_omitted.extend(["其他模块的 imports/definitions 详情（保留其路径索引）",
                              "与目标模块无关的 inventory 非必要字段"])
        stage_c = analysis.get("stageC", {})
        related = [item for item in stage_c.get("relations", [])
                   if item.get("from") == module_id or item.get("to") == module_id]
        source_analysis = {
            "project": analysis.get("project"),
            "stageB": {"layers": analysis.get("stageB", {}).get("layers", []), "modules": modules},
            "stageC": {"status": stage_c.get("status"), "relations": related},
        }
        analysis_included = ["stageB.layers", "stageB.modules（只读端点目录）",
                             f"stageC.relations 中与 {module_id} 相连的关系（{len(related)} 条）"]
        analysis_omitted = ["stageA 候选详情", "其他模块间既有关系", "stageD"]
        facts_included.append(f"目标证据路径：{', '.join(sorted(target_paths)) or '未提供'}")
    else:  # D
        assert analysis is not None
        project_facts["moduleIndex"] = module_index
        facts_included.append("moduleIndex[*].path/module（用于 coverage 与路径核对）")
        facts_omitted.extend(["modules[*].imports/definitions/entrypoints AST 详情",
                              "inventory.directories 与 nonPythonFiles（保留清单摘要及入口/配置路径）"])
        stage_names = ["stageA", "stageB", "stageC"]
        source_analysis = {key: analysis.get(key) for key in ("project", "coverage", *stage_names)}
        if analysis.get("stageD") is not None:
            source_analysis["stageD"] = analysis["stageD"]
            analysis_included.append("stageD（当前版本，供修订）")
        analysis_included.extend(["stageA", "stageB", "stageC（D 审计必需的完整上下文）"])
        analysis_omitted = ["无关的 diagram.schema.json", "非事实源码正文"]

    return (project_facts, source_analysis, facts_included, facts_omitted,
            analysis_included, analysis_omitted)


def build_work_order(*, facts: dict, analysis_schema: dict, diagram_schema: dict,
                     stage: str | None = None, analysis: dict | None = None,
                     module_id: str | None = None, slim: bool = False) -> str:
    rules_path = analysis_rules_path()
    rules = rules_path.read_text(encoding="utf-8")
    if not slim:
        if stage is not None or module_id is not None or analysis is not None:
            raise ValueError("默认完整工作单不接受 --stage、--module-id 或 --analysis；需要阶段筛选时使用 --slim-input")
        return f"""# 架构图语义抽象工作单

## 强制阶段与唯一权威规则

{rules.strip()}

## 项目结构索引事实

本工作单仅适用于 Python 项目。若 facts 显示 Python 源文件数为 0，停止语义分析并提示用户当前不支持非 Python 项目。混合仓库只分析 Python 子系统；非 Python 文件仅作路径盘点，不归纳其内部职责或关系。只有 Python 源码直接证明跨边界调用时，才将对端作为外部端点记录。

以下 JSON 只用于代码导航，不能替代 Python 源码阅读。扫描器为 Python 源文件提取 AST 结构；模块职责与关系必须回到 Python 源码核实：

```json
{_json(facts)}
```

## JSON Schema (`schemas/diagram.schema.json`)

```json
{_json(diagram_schema)}
```

## 阶段化分析 JSON Schema (`schemas/analysis.schema.json`)

```json
{_json(analysis_schema)}
```

先按 A-D 生成并审计 `analysis.json`，然后由 `architecture-diagram analysis-reports analysis.json -o <输出目录>` 自动生成 `modules.md`、`relations.md`、`main-paths.md`。不要手写这些派生清单。后续分层、图面、结构确认、签发、视觉验收和质量检查遵循当前 `SKILL.md`。
"""

    if stage not in _STAGE_NAMES:
        raise ValueError("启用 --slim-input 时必须指定 --stage A、B、C 或 D")
    if stage == "A" and (analysis is not None or module_id is not None):
        raise ValueError("阶段 A 不需要 --analysis 或 --module-id")
    if stage in {"B", "C", "D"} and analysis is None:
        raise ValueError(f"阶段 {stage} 必须提供 --analysis")
    if stage == "C" and not module_id:
        raise ValueError("阶段 C 必须提供 --module-id；一次只生成一个模块的关系工作单")
    if stage != "C" and module_id is not None:
        raise ValueError("--module-id 仅用于阶段 C")

    (selected_facts, selected_analysis, facts_included, facts_omitted,
     analysis_included, analysis_omitted) = _selected_inputs(facts, analysis, stage, module_id)
    selected_schema = _stage_schema(analysis_schema, stage)
    stage_rules = _stage_rules(rules, stage)
    manifest = {
        "mode": "stage-scoped",
        "stage": stage,
        "moduleId": module_id,
        "ruleSource": rules_path.as_posix(),
        "factsOriginalBytes": len(_json(facts).encode("utf-8")),
        "factsIncludedBytes": len(_json(selected_facts).encode("utf-8")),
        "factsIncluded": facts_included,
        "factsOmitted": facts_omitted,
        "analysisIncluded": analysis_included,
        "analysisOmitted": analysis_omitted,
        "schemaIncluded": [f"analysis.schema.json::$defs[{', '.join(selected_schema['$defs'])}]",
                            f"analysis.schema.json::properties.{_STAGE_NAMES[stage]}"],
        "schemaOmitted": ["diagram.schema.json", f"analysis.schema.json 中除 {_STAGE_NAMES[stage]} 外的阶段及未引用定义"],
    }
    return f"""# 架构图阶段 {stage} 工作单

## 阶段范围

本工作单只执行阶段 {stage}。严格遵循下方唯一权威阶段规则，并按项目实际语言阅读仓库源码；结构索引 facts 只是导航线索，未被自动解析的语言仍须人工读取。输出只包含可合并回 `analysis.json` 的 `{_STAGE_NAMES[stage]}` 字段，不改写其他阶段，不生成图、不签发、不渲染。

## 输入筛选记录

以下清单说明本次实际提供与省略的上下文，省略项仍可从项目源码中读取，不代表不需要检查。

```json
{_json(manifest)}
```

## 本阶段规则（由唯一权威来源生成）

来源：`{rules_path.as_posix()}`

{stage_rules}

## 筛选后的结构索引 facts

```json
{_json(selected_facts)}
```
""" + (f"""
## 必要的已有 analysis 上下文

```json
{_json(selected_analysis)}
```
""" if selected_analysis is not None else "") + f"""
## 本阶段 JSON Schema 片段

只输出通过此片段校验的 `{_STAGE_NAMES[stage]}` 对象，合并时保留 analysis.json 中其他阶段的数据。

```json
{_json(selected_schema)}
```
"""
