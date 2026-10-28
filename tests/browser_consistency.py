"""Run browser consistency checks against one real project IR and its drilldown."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from architecture_diagram.capture import _browser_path, _node_playwright  # noqa: E402
from architecture_diagram.layout import layout_diagram  # noqa: E402
from architecture_diagram.render import render_html  # noqa: E402

FIXTURE = ROOT / "tests/layout_fixtures/shopcare-baseline.json"
DRIVER = ROOT / "tests/browser_consistency_matrix.mjs"
REPORT_JSON = ROOT / "docs/browser-consistency-current.json"
REPORT_MD = ROOT / "docs/browser-consistency-current.md"
OUTPUT = ROOT / "outputs/browser-consistency-current"
MAX_PIXEL_DIFFERENCE_PERCENT = 0.5


def _edge_path() -> str | None:
    candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    return str(next((path for path in candidates if path.is_file()), "")) or None


def _read_rgb(image_path: str) -> Image.Image:
    with Image.open(image_path) as image:
        return image.convert("RGB").copy()


def _pixel_difference(reference: Image.Image, actual: Image.Image) -> dict:
    diff = ImageChops.difference(reference, actual)
    means = ImageStat.Stat(diff).mean
    mae_percent = sum(means) / (3 * 255) * 100
    raw = diff.tobytes()
    changed = sum(1 for index in range(0, len(raw), 3) if raw[index] or raw[index + 1] or raw[index + 2])
    return {"meanAbsoluteDifferencePercent": round(mae_percent, 5),
            "changedPixelPercent": round(changed / max(1, diff.width * diff.height) * 100, 5),
            "thresholdPercent": MAX_PIXEL_DIFFERENCE_PERCENT,
            "passed": mae_percent <= MAX_PIXEL_DIFFERENCE_PERCENT}


def main() -> int:
    runtime = _node_playwright()
    chromium_executable = _browser_path(None)
    if not runtime or not chromium_executable:
        print("阶段 2 浏览器矩阵未运行：当前环境缺少 Playwright 或 Chromium/Chrome。", file=sys.stderr)
        return 2
    node, playwright_module = runtime
    browsers = [{"name": "Chromium", "executable": chromium_executable}]
    edge = _edge_path()
    if edge:
        browsers.append({"name": "Edge", "executable": edge})

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    diagram = payload["diagram"]
    layout = layout_diagram(diagram, backend="builtin")
    html = render_html(diagram, layout, backend="builtin")
    temp_root = ROOT / ".tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="browser-consistency-", dir=temp_root) as temporary:
        work = Path(temporary)
        html_path = work / "architecture-diagram.html"
        html_path.write_text(html, encoding="utf-8")
        screenshot_dir = work / "screenshots"
        screenshot_dir.mkdir()
        config_path = work / "config.json"
        raw_report = work / "matrix.json"
        config_path.write_text(json.dumps({"htmlPath": str(html_path), "screenshotDir": str(screenshot_dir),
                                          "browsers": browsers}, ensure_ascii=False), encoding="utf-8")
        process = subprocess.run([node, str(DRIVER), str(config_path), playwright_module, str(raw_report)],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=240)
        if not raw_report.is_file():
            print(process.stderr.strip() or process.stdout.strip() or "浏览器矩阵没有生成报告", file=sys.stderr)
            return process.returncode or 1
        report = json.loads(raw_report.read_text(encoding="utf-8"))

        reference_entry = next((item for item in report["screenshots"] if
                                item["browser"] == "Chromium" and item["protocol"] == "file" and
                                item["state"] == "fresh" and item["width"] == 1600 and item.get("normalized") and
                                item.get("view") != "drilldown"), None)
        if not reference_entry:
            print("没有取得 Chromium/file/fresh/1600 的画布截图基准。", file=sys.stderr)
            return process.returncode or 1
        reference = _read_rgb(reference_entry["path"])
        target_width, target_height = reference.size
        pixel_results = []
        for entry in report["screenshots"]:
            if entry.get("view") == "drilldown" or not entry.get("normalized"):
                continue
            actual = _read_rgb(entry["path"])
            if actual.size != reference.size:
                raise RuntimeError(f"规范截图尺寸不一致：{entry['path']} 为 {actual.size}，基准为 {reference.size}")
            delta = _pixel_difference(reference, actual)
            pixel_results.append({key: entry[key] for key in ("browser", "protocol", "state", "width")} |
                                 {"imageSize": list(actual.size)} | delta)

        main_target = OUTPUT / "main-chromium-file-fresh-1600.png"
        shutil.copy2(reference_entry["path"], main_target)
        child_entry = next((item for item in report["screenshots"] if item.get("view") == "drilldown"), None)
        child_target = OUTPUT / "drilldown-chromium-file-fresh-1600.png"
        if child_entry:
            shutil.copy2(child_entry["path"], child_target)

        report["pixelComparison"] = {
            "normalization": {"viewportWidth": 1600, "viewportHeight": 900,
                              "imageWidth": target_width, "imageHeight": target_height,
                              "resampling": "无；直接比较交互页 SVG locator 的同尺寸截图",
                              "metric": "RGB mean absolute error / 255"},
            "reference": {"browser": "Chromium", "protocol": "file", "state": "fresh", "width": 1600},
            "thresholdPercent": MAX_PIXEL_DIFFERENCE_PERCENT,
            "comparisons": pixel_results,
            "passed": all(item["passed"] for item in pixel_results),
        }
        report["audit"] = {
            "matrixCompleted": bool(report["results"]),
            "allBrowsersAvailable": all(item["available"] for item in report["browserAvailability"]),
            "geometryInvariant": all(width["localGeometryMaxDeltaPx"] <= 0.001
                                      for result in report["results"] for width in result["widths"]),
            "noHorizontalOverflow": all(width["documentWidth"] <= width["width"] and
                                         width["workspaceScrollWidth"] <= width["workspaceWidth"]
                                         for result in report["results"] for width in result["widths"]),
            "drilldownResetsScroll": all(result["drilldown"]["scrollAfter"] == 0 and
                                         result["drilldown"]["scrollAfterBack"] == 0
                                         for result in report["results"]),
            "staleStateDiscarded": all(result["state"] not in {"stale", "invalid"} or not result["storageAvailable"] or
                                       (result["notice"] == "布局已更新，已恢复自动布局")
                                       for result in report["results"]),
            "dragResetWorks": all(not result["dragPersistence"] or result["dragPersistence"]["resetWorks"]
                                  for result in report["results"]),
            "noPageErrors": all(not result["pageErrors"] for result in report["results"]),
            "normalizedPixelDifferenceAtMostThreshold": report["pixelComparison"]["passed"],
        }
        report["deliverables"] = {"mainScreenshot": str(main_target),
                                  "drilldownScreenshot": str(child_target) if child_entry else None}
        required = ["matrixCompleted", "geometryInvariant", "noHorizontalOverflow", "drilldownResetsScroll",
                    "staleStateDiscarded", "dragResetWorks", "noPageErrors", "normalizedPixelDifferenceAtMostThreshold"]
        report["passed"] = all(report["audit"][key] for key in required)

    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    browser_summary = "; ".join("{} {}".format(item["name"], item.get("version", "不可用"))
                                 for item in report["browserAvailability"])
    lines = ["# 阶段 2 浏览器一致性验收", "",
             f"矩阵组合：{len(report['results'])}；视口宽度 1280 / 1440 / 1920；设备像素比 2；file:// 与 http；fresh/stale localStorage。",
             f"浏览器：{browser_summary}。",
             "", "| 浏览器 | 协议 | 状态 | 1280/1440/1920 坐标差 | 横向溢出 | 下钻滚动复位 |",
             "|---|---|---|---:|---|---|"]
    for result in report["results"]:
        delta = max((item["localGeometryMaxDeltaPx"] for item in result["widths"]), default=0)
        no_overflow = all(item["documentWidth"] <= item["width"] and
                          item["workspaceScrollWidth"] <= item["workspaceWidth"] for item in result["widths"])
        lines.append(f"| {result['browser']} | {result['protocol']} | {result['state']} | {delta:.3f}px | "
                     f"{'通过' if no_overflow else '失败'} | "
                     f"{'通过' if result['drilldown']['scrollAfter'] == 0 and result['drilldown']['scrollAfterBack'] == 0 else '失败'} |")
    lines.extend(["", "## 归一化画布像素差异", "", f"先在 1280/1440/1920 逐视口检查几何，再固定使用 1600×900 viewport 捕获交互页 SVG。"
                  f"所有截图为 {target_width}×{target_height}，不做缩放重采样，以避免不同尺寸下文字栅格化差异；"
                  f"判定指标为 RGB 平均绝对差，阈值 {MAX_PIXEL_DIFFERENCE_PERCENT:.1f}%。", "",
                  "| 浏览器 | 协议 | 状态 | 视口 | 平均像素差 | 判定 |", "|---|---|---|---:|---:|---|"])
    for item in pixel_results:
        lines.append(f"| {item['browser']} | {item['protocol']} | {item['state']} | {item['width']} | "
                     f"{item['meanAbsoluteDifferencePercent']:.4f}% | {'通过' if item['passed'] else '失败'} |")
    lines.extend(["", "## 总体验收", "", f"结果：{'通过' if report['passed'] else '未通过'}。", "",
                  f"主图截图：[PNG]({report['deliverables']['mainScreenshot']})。",
                  f"下钻截图：[PNG]({report['deliverables']['drilldownScreenshot'] or '未生成'})。",
                  f"完整矩阵：[JSON]({REPORT_JSON.as_posix()})。", ""])
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "audit": report["audit"],
                      "pixelMaxPercent": max((item["meanAbsoluteDifferencePercent"] for item in pixel_results), default=0),
                      "combinations": len(report["results"]), "report": str(REPORT_JSON)}, ensure_ascii=False, indent=2))
    return 0 if report["passed"] and process.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
