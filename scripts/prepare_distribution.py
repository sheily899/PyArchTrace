"""Sync the installable Skill payload and build a curated OpenAI plugin ZIP."""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "architecture-diagram"
SUPPORT_FILES = (
    "references/analysis-stages.md",
    "references/visual-review-schema.json",
    "docs/layout-contract-v2.md",
    "docs/edge-group-routing.md",
    "schemas/analysis.schema.json",
    "schemas/diagram.schema.json",
)
PLUGIN_FILES = (
    "plugin.json",
    "LICENSE",
    "assets/pyarchtrace-icon.svg",
)


def project_version() -> str:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', pyproject)
    if not match:
        raise ValueError("pyproject.toml 中找不到项目版本")
    return match.group(1)


def sync_skill_payload() -> None:
    for relative in SUPPORT_FILES:
        source = ROOT / relative
        target = SKILL_ROOT / relative
        if not source.is_file():
            raise FileNotFoundError(f"Skill 依赖文件不存在：{source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())

    skill = SKILL_ROOT / "SKILL.md"
    if not skill.is_file():
        raise FileNotFoundError(f"Skill 入口不存在：{skill}")


def validate_package() -> tuple[dict, list[str]]:
    manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
    expected_version = project_version()
    if manifest.get("version") != expected_version:
        raise ValueError(
            f"plugin.json 版本 {manifest.get('version')} 与项目版本 {expected_version} 不一致"
        )

    interface = manifest.get("extensions", {}).get("com.openai", {}).get("interface", {})
    for field in ("displayName", "shortDescription", "longDescription", "developerName", "category"):
        if not interface.get(field):
            raise ValueError(f"plugin.json 缺少目录字段：{field}")
    if len(interface["displayName"]) > 30 or len(interface["shortDescription"]) > 30:
        raise ValueError("插件名称或短描述超过 30 字符")
    if len(interface["longDescription"]) > 4000:
        raise ValueError("插件长描述超过 4000 字符")
    if any(len(prompt) > 128 for prompt in interface.get("defaultPrompt", [])):
        raise ValueError("默认提示超过 128 字符")

    packaged = [*PLUGIN_FILES, "skills/architecture-diagram/SKILL.md"]
    packaged.extend(f"skills/architecture-diagram/{path}" for path in SUPPORT_FILES)
    packaged.append("skills/architecture-diagram/agents/openai.yaml")
    missing = [path for path in packaged if not (ROOT / path).is_file()]
    if missing:
        raise FileNotFoundError("插件包缺少文件：" + ", ".join(missing))
    return manifest, packaged


def build_zip(packaged: list[str], version: str) -> Path:
    output_dir = ROOT / "dist" / "openai-plugin"
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"PyArchTrace-{version}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(packaged):
            bundle.write(ROOT / path, arcname=path)
    return archive


def main() -> None:
    sync_skill_payload()
    manifest, packaged = validate_package()
    archive = build_zip(packaged, manifest["version"])
    print(f"插件包：{archive}")
    print(f"版本：{manifest['version']}")
    print(f"包含文件：{len(packaged)}")
    print(f"压缩包大小：{archive.stat().st_size:,} bytes")
    for path in sorted(packaged):
        print(f"  {path}")


if __name__ == "__main__":
    main()
