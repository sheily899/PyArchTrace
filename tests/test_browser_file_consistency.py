from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageStat

from architecture_diagram.capture import _browser_path, _node_playwright
from architecture_diagram.layout import layout_diagram
from architecture_diagram.render import render_html


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "layout_fixtures" / "shopcare-baseline.json"
DRIVER = ROOT / "tests" / "browser_consistency_matrix.mjs"


def test_file_protocol_layout_state_and_interactions(tmp_path: Path):
    runtime = _node_playwright()
    executable = _browser_path(None)
    if not runtime or not executable:
        pytest.skip("需要本机 Node Playwright 与 Chromium/Chrome")
    node, playwright_module = runtime
    diagram = json.loads(FIXTURE.read_text(encoding="utf-8"))["diagram"]
    html_path = tmp_path / "architecture-diagram.html"
    html_path.write_text(
        render_html(diagram, layout_diagram(diagram, backend="builtin"), backend="builtin"),
        encoding="utf-8",
    )
    screenshot_dir = tmp_path / "screenshots"
    screenshot_dir.mkdir()
    config_path = tmp_path / "config.json"
    report_path = tmp_path / "matrix.json"
    config_path.write_text(json.dumps({
        "htmlPath": str(html_path),
        "screenshotDir": str(screenshot_dir),
        "browsers": [{"name": "Chromium", "executable": executable}],
        "protocols": ["file"],
    }), encoding="utf-8")

    completed = subprocess.run(
        [node, str(DRIVER), str(config_path), playwright_module, str(report_path)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
    )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert len(report["results"]) == 3

    expected_notice = "布局已更新，已恢复自动布局"
    for result in report["results"]:
        assert all(width["localGeometryMaxDeltaPx"] <= 0.001 for width in result["widths"])
        assert result["drilldown"]["scrollAfter"] == result["drilldown"]["scrollAfterBack"] == 0
        assert not result["pageErrors"]
        if result["state"] == "fresh":
            assert result["dragPersistence"]["resetWorks"]
        else:
            assert result["notice"] == expected_notice

    screenshots = [item for item in report["screenshots"] if item.get("normalized")]
    assert len(screenshots) == 3
    reference_item = next(item for item in screenshots if item["state"] == "fresh")
    with Image.open(reference_item["path"]) as image:
        reference = image.convert("RGB").copy()
    for item in screenshots:
        with Image.open(item["path"]) as image:
            current = image.convert("RGB").copy()
        assert current.size == reference.size
        difference = ImageChops.difference(reference, current)
        mean_percent = sum(ImageStat.Stat(difference).mean) / (3 * 255) * 100
        assert mean_percent <= 0.5

