"""Skill 与运行时代码共用的渲染版本契约。"""

from __future__ import annotations

import re
import sys
from pathlib import Path


RENDERER_VERSION = "architecture-renderer-v1"
LAYOUT_ALGORITHM_VERSION = "architecture-swimlane-v10"
_VERSION_PATTERN = re.compile(
    r"<!-- architecture-diagram-version: renderer=([^;]+); layout=([^ ]+) -->"
)


def skill_document_path(override: str | Path | None = None) -> Path:
    if override is not None:
        return Path(override)
    candidates = (
        Path(__file__).resolve().parents[2] / "SKILL.md",
        Path(sys.prefix) / "share" / "architecture-diagram" / "SKILL.md",
    )
    return next((path for path in candidates if path.is_file()), candidates[0])


def version_mismatches(skill_path: str | Path | None = None) -> list[str]:
    path = skill_document_path(skill_path)
    if not path.is_file():
        return [f"找不到 Skill 版本说明：{path}"]
    content = path.read_text(encoding="utf-8")
    match = _VERSION_PATTERN.search(content)
    if not match:
        return [f"{path} 缺少 architecture-diagram-version 标记"]
    documented_renderer, documented_layout = match.groups()
    errors = []
    if documented_renderer != RENDERER_VERSION:
        errors.append(
            f"Skill 渲染器版本为 {documented_renderer}，运行时代码为 {RENDERER_VERSION}"
        )
    if documented_layout != LAYOUT_ALGORITHM_VERSION:
        errors.append(
            f"Skill 布局版本为 {documented_layout}，运行时代码为 {LAYOUT_ALGORITHM_VERSION}"
        )
    return errors
