"""只读软件项目盘点器；自动提取 Python AST 索引，但绝不导入或执行目标项目。"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Iterable

from .scan_config import DEFAULT_EXCLUDED_DIRS, EXCLUSION_RULES_VERSION, LEGACY_EXCLUDED_DIRS

_DEPENDENCY_MANIFESTS = {
    "package.json", "requirements.txt", "pyproject.toml", "poetry.lock", "Pipfile",
    "Pipfile.lock", "environment.yml", "environment.yaml", "pom.xml", "build.gradle",
    "build.gradle.kts", "Cargo.toml", "go.mod", "Gemfile", "composer.json", "uv.lock",
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "gradle.properties",
}
_SENSITIVE_NAMES = {".env", ".env.local", ".env.production", ".env.development"}
_ENTRY_BASENAMES = {"main", "app", "index", "server", "manage", "wsgi", "asgi", "run"}
_ENTRY_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".kt", ".rs", ".php", ".rb", ".sh"}


def _is_sensitive_path(relative: Path) -> bool:
    name = relative.name.lower()
    return name in _SENSITIVE_NAMES or name.startswith(".env.") or name.endswith((".pem", ".key", ".p12", ".pfx"))


def _is_excluded_component(name: str, excluded: set[str], included: set[str]) -> bool:
    return name not in included and (name in excluded or name.startswith("."))


def _scan_tree(root: Path, excluded: set[str], included: set[str]) -> tuple[dict, list[Path]]:
    files: list[Path] = []
    python_files: list[Path] = []
    directories: list[str] = []
    excluded_paths: set[str] = set()
    sensitive_paths: set[str] = set()
    for current, dirnames, filenames in os.walk(root, topdown=True):
        current_path = Path(current)
        relative_dir = current_path.relative_to(root)
        if relative_dir.parts:
            directories.append(relative_dir.as_posix() + "/")
        kept_dirs = []
        for name in sorted(dirnames):
            relative = relative_dir / name
            if _is_excluded_component(name, excluded, included):
                excluded_paths.add(relative.as_posix() + "/")
            else:
                kept_dirs.append(name)
        dirnames[:] = kept_dirs
        for name in sorted(filenames):
            relative = relative_dir / name
            if _is_sensitive_path(relative):
                sensitive_paths.add(relative.as_posix())
                continue
            excluded_part = next((part for part in relative.parts
                                  if _is_excluded_component(part, excluded, included)), None)
            if excluded_part:
                prefix = relative.parts[:relative.parts.index(excluded_part) + 1]
                excluded_paths.add(Path(*prefix).as_posix() + "/")
                continue
            files.append(relative)
            if relative.suffix == ".py":
                python_files.append(relative)

    manifests = sorted(path.as_posix() for path in files if path.name in _DEPENDENCY_MANIFESTS)
    containers = sorted(
        path.as_posix() for path in files
        if path.name.lower().startswith("dockerfile")
        or path.name.lower().startswith("docker-compose")
        or (path.name.lower().startswith("compose") and path.suffix.lower() in {".yml", ".yaml"})
    )
    configs = sorted(
        path.as_posix() for path in files
        if path.suffix.lower() in {".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".json", ".properties", ".xml"}
        and path.name not in _DEPENDENCY_MANIFESTS
    )
    entry_files = sorted(
        path.as_posix() for path in files
        if path.stem.lower() in _ENTRY_BASENAMES and path.suffix.lower() in _ENTRY_SUFFIXES
    )
    return {
        "directories": sorted(directories),
        "fileCount": len(files),
        "dependencyManifests": manifests,
        "configurationFiles": configs,
        "containerFiles": containers,
        "entryFiles": entry_files,
        "nonPythonFiles": sorted(path.as_posix() for path in files if path.suffix.lower() != ".py"),
        "excludedPaths": sorted(excluded_paths),
        "sensitivePaths": sorted(sensitive_paths),
    }, sorted(python_files)


def _legacy_inventory(root: Path, excluded: set[str]) -> dict:
    """Keep the compatibility inventory semantics for the default scan mode."""
    files: list[Path] = []
    directories: list[str] = []
    excluded_paths: set[str] = set()
    sensitive_paths: set[str] = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        parts = relative.parts
        if path.is_file() and _is_sensitive_path(relative):
            sensitive_paths.add(relative.as_posix())
            continue
        excluded_part = next((part for part in parts if part in excluded or part.startswith(".")), None)
        if excluded_part:
            prefix = parts[:parts.index(excluded_part) + 1]
            excluded_paths.add(Path(*prefix).as_posix() + "/")
            continue
        if path.is_dir():
            directories.append(relative.as_posix() + "/")
        elif path.is_file():
            files.append(relative)

    manifests = sorted(path.as_posix() for path in files if path.name in _DEPENDENCY_MANIFESTS)
    containers = sorted(
        path.as_posix() for path in files
        if path.name.lower().startswith("dockerfile")
        or path.name.lower().startswith("docker-compose")
        or (path.name.lower().startswith("compose") and path.suffix.lower() in {".yml", ".yaml"})
    )
    configs = sorted(
        path.as_posix() for path in files
        if path.suffix.lower() in {".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".json", ".properties", ".xml"}
        and path.name not in _DEPENDENCY_MANIFESTS
    )
    entry_files = sorted(
        path.as_posix() for path in files
        if path.stem.lower() in _ENTRY_BASENAMES and path.suffix.lower() in _ENTRY_SUFFIXES
    )
    return {
        "directories": sorted(directories),
        "fileCount": len(files),
        "dependencyManifests": manifests,
        "configurationFiles": configs,
        "containerFiles": containers,
        "entryFiles": entry_files,
        "nonPythonFiles": sorted(path.as_posix() for path in files if path.suffix.lower() != ".py"),
        "excludedPaths": sorted(excluded_paths),
        "sensitivePaths": sorted(sensitive_paths),
    }


def _discover_files(root: Path, excluded_dirs: set[str]) -> Iterable[Path]:
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if any(part in excluded_dirs for part in relative.parts[:-1]):
            continue
        if any(part.startswith(".") for part in relative.parts[:-1]):
            continue
        yield path


def _module_name(relative: Path) -> str:
    parts = list(relative.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


class _FactsVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.imports: list[dict] = []
        self.definitions: list[dict] = []
        self.entrypoints: list[dict] = []
        self._scope = 0

    def visit_Import(self, node: ast.Import) -> None:
        for item in node.names:
            self.imports.append({"module": item.name, "line": node.lineno, "kind": "import"})

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.imports.append({"module": "." * node.level + (node.module or ""), "line": node.lineno, "kind": "from"})

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.definitions.append({"name": node.name, "kind": "function", "line": node.lineno, "end_line": node.end_lineno})
        if self._scope == 0 and node.name in {"main", "run", "create_app"}:
            self.entrypoints.append({"kind": "conventional_function", "name": node.name, "line": node.lineno})
        self._scope += 1
        self.generic_visit(node)
        self._scope -= 1

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.definitions.append({"name": node.name, "kind": "class", "line": node.lineno, "end_line": node.end_lineno})
        self._scope += 1
        self.generic_visit(node)
        self._scope -= 1

    def visit_If(self, node: ast.If) -> None:
        if self._scope == 0 and _is_main_guard(node.test):
            self.entrypoints.append({"kind": "main_guard", "line": node.lineno})
        self.generic_visit(node)


def _is_main_guard(expression: ast.expr) -> bool:
    if isinstance(expression, ast.Compare) and len(expression.ops) == 1 and len(expression.comparators) == 1:
        left, right = expression.left, expression.comparators[0]
        return (
            isinstance(left, ast.Name) and left.id == "__name__"
            and isinstance(right, ast.Constant) and right.value == "__main__"
        ) or (
            isinstance(right, ast.Name) and right.id == "__name__"
            and isinstance(left, ast.Constant) and left.value == "__main__"
        )
    return False


def scan_project(project_path: str | Path, *, excluded_dirs: set[str] | None = None,
                 included_dirs: set[str] | None = None, optimized: bool = False) -> dict:
    """提取模块、导入、定义和入口证据；不保留代码正文、字面量或绝对路径。"""
    root = Path(project_path).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(root)
    included = set(included_dirs or ())
    if optimized:
        excluded = (DEFAULT_EXCLUDED_DIRS | set(excluded_dirs or ())) - included
        inventory, python_files = _scan_tree(root, excluded, included)
    else:
        if included:
            raise ValueError("--include-dir 仅适用于 --optimized-scan")
        excluded = LEGACY_EXCLUDED_DIRS | set(excluded_dirs or ())
        inventory = _legacy_inventory(root, excluded)
        python_files = [path.relative_to(root) for path in _discover_files(root, excluded)]
    modules: list[dict] = []
    for relative in python_files:
        file_path = root / relative
        try:
            source = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            source = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=relative.as_posix())
        visitor = _FactsVisitor()
        visitor.visit(tree)
        lines = source.splitlines()
        modules.append({
            "path": relative.as_posix(),
            "module": _module_name(relative),
            "line_count": len(lines),
            "imports": sorted(visitor.imports, key=lambda item: (item["line"], item["module"])),
            "definitions": sorted(visitor.definitions, key=lambda item: (item["line"], item["name"])),
            "entrypoints": sorted(visitor.entrypoints, key=lambda item: item["line"]),
        })
    entrypoints = [
        {"path": module["path"], **entry}
        for module in modules for entry in module["entrypoints"]
    ]
    facts = {
        "formatVersion": 1,
        "project": {"name": root.name},
        "summary": {
            "python_files": len(modules),
            "code_lines": sum(module["line_count"] for module in modules),
        },
        "inventory": inventory,
        "coverage": {
            "analyzed": {
                "scope": "项目内未被排除的 Python 源文件，仅解析 AST 结构",
                "pythonFiles": [module["path"] for module in modules],
                "fileCount": len(modules),
                "codeLines": sum(module["line_count"] for module in modules),
            },
            "notAnalyzed": [
                {"path": path, "reason": "目录命中默认或用户指定排除规则"}
                for path in inventory["excludedPaths"]
            ] + [
                {"path": path, "reason": "敏感文件名命中规则；仅记录路径，未读取内容"}
                for path in inventory["sensitivePaths"]
            ] + ([{
                "path": "项目中的非 Python 文件",
                "reason": "只盘点路径类型；未读取内容或语义分析。依赖清单、配置、容器文件与入口文件需在语义分析阶段按需只读核验。",
            }] if inventory["fileCount"] > len(modules) else []),
        },
        "modules": modules,
        "entrypoints": entrypoints,
        "limitations": [
            "AST 结果是结构事实，不代表业务职责或运行时一定会调用。",
            "动态导入、插件注册、反射与运行时注入无法仅凭静态扫描完整识别。",
            "测试、评测、构建、部署目录按默认排除规则跳过；可通过命令行覆盖。",
        ],
    }
    if optimized:
        facts["exclusionRulesVersion"] = EXCLUSION_RULES_VERSION
        facts["scanConfig"] = {
            "mode": "optimized-opt-in",
            "exclusionRulesVersion": EXCLUSION_RULES_VERSION,
            "excludedDirectoryNames": sorted(excluded),
            "includedOverrides": sorted(included),
            "hiddenDirectoryRule": "跳过名称以点号开头的目录；include-dir 可覆盖",
        }
    return facts
