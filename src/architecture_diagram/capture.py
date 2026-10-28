"""通过本机 Playwright + Chrome/Edge 打开 file:// HTML 并截图。"""

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path


def _browser_path(explicit: str | None) -> str | None:
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise FileNotFoundError(f"指定浏览器不存在：{path}")
        return str(path)
    candidates = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe",
    ]
    return str(next((path for path in candidates if path.is_file()), "")) or None


def _node_playwright() -> tuple[str, str] | None:
    candidates = []
    node_on_path = shutil.which("node")
    if node_on_path:
        candidates.append(Path(node_on_path))
    user_root = Path.home()
    candidates.extend([
        user_root / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe",
        user_root / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node",
    ])
    module_candidates = [
        user_root / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs",
    ]
    helper = Path(__file__).parent / "scripts" / "capture_with_playwright.mjs"
    for node in candidates:
        if not node.is_file():
            continue
        for module in module_candidates:
            if module.is_file():
                return str(node), str(module)
        # 系统 Node 可解析当前工具环境中的 Playwright 包时，也可以作为驱动。
        probe = subprocess.run([str(node), "--input-type=module", "-e", "import.meta.resolve('playwright')"],
                               capture_output=True, text=True, timeout=5)
        if probe.returncode == 0:
            resolved = probe.stdout.strip().strip("'\"")
            if resolved.startswith("file:"):
                from urllib.parse import unquote, urlparse
                module_path = unquote(urlparse(resolved).path)
                if os.name == "nt" and module_path.startswith("/"):
                    module_path = module_path[1:]
                if Path(module_path).is_file():
                    return str(node), module_path
    return None


def _png_dimensions(data: bytes) -> tuple[int, int]:
    """读取 PNG 的 IHDR 尺寸，供截图完整性检查使用。"""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError("截图不是有效 PNG 或缺少 IHDR 头")
    return struct.unpack(">II", data[16:24])


def _verify_capture_size(png_file: Path, dom: dict, scale: int) -> dict:
    width, height = _png_dimensions(png_file.read_bytes()[:24])
    view_box = [float(value) for value in (dom.get("viewBox") or "").split()]
    if len(view_box) != 4:
        raise RuntimeError("截图页面没有有效 SVG viewBox")
    rect = dom.get("svgClientRect") or {}
    css_width = float(rect.get("width", view_box[2]))
    css_height = float(rect.get("height", view_box[3]))
    expected = (round(css_width * scale), round(css_height * scale))
    # Chromium rounds the SVG's fractional CSS bounds when forming a locator
    # screenshot. At 2x that can add a device pixel on each edge; a positive
    # surplus is safe, while any shortfall could mean the diagram was clipped.
    surplus = (width - expected[0], height - expected[1])
    if any(delta < 0 or delta > 2 for delta in surplus):
        raise RuntimeError(
            f"截图尺寸 {width}x{height} 与完整图面 {expected[0]}x{expected[1]} 不符，"
            "存在裁切或异常边界差异"
        )
    return {"width": width, "height": height, "expected_width": expected[0],
            "expected_height": expected[1], "rounding_surplus_px": list(surplus)}


def _capture_via_node(node: str, module: str, html_file: Path, png_file: Path, executable: str | None,
                      viewport: tuple[int, int], scale: int, omit_drill_icons: bool) -> dict | None:
    helper = Path(__file__).parent / "scripts" / "capture_with_playwright.mjs"
    if not helper.is_file():
        return None
    process = subprocess.run([node, str(helper), str(html_file), str(png_file), executable or "",
                              str(viewport[0]), str(viewport[1]), str(scale), module,
                              "1" if omit_drill_icons else "0"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
    if process.returncode != 0:
        raise RuntimeError(f"Playwright/Chrome 截图失败：{process.stderr.strip() or process.stdout.strip()}")
    try:
        return json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"截图驱动没有返回有效报告：{process.stdout[:500]}") from exc


def capture_html(html_path: str | Path, png_path: str | Path, *, browser_executable: str | None = None,
                 viewport: tuple[int, int] = (1600, 900), scale: int = 2,
                 omit_drill_icons: bool = False) -> dict:
    """截取本地 HTML 的真实浏览器渲染；输出截图及浏览器运行诊断。"""
    html_file = Path(html_path).resolve(strict=True)
    png_file = Path(png_path).resolve()
    png_file.parent.mkdir(parents=True, exist_ok=True)
    executable = _browser_path(browser_executable)
    node_runtime = _node_playwright()
    if node_runtime:
        browser_result = _capture_via_node(*node_runtime, html_file, png_file, executable, viewport, scale,
                                           omit_drill_icons)
        image_size = _verify_capture_size(png_file, browser_result["dom"], scale)
        return {"html": str(html_file), "screenshot": str(png_file), "browser": executable or "Playwright 默认 Chromium",
                "url_scheme": "file", "http_status": browser_result["httpStatus"],
                "viewport": {"width": viewport[0], "height": viewport[1], "scale": scale},
                "page_errors": browser_result["errors"], "dom": browser_result["dom"],
                "screenshot_dimensions": image_size, "driver": "Node Playwright",
                "omitted_drill_icons": bool(omit_drill_icons and browser_result["dom"].get("drillIconCount") == 0)}
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("未发现本机 Node Playwright 或 Python Playwright；安装 Python 包后重试。") from exc
    launch_args = {"headless": True}
    if executable:
        launch_args["executable_path"] = executable
    errors: list[str] = []
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(**launch_args)
        except Exception as exc:
            raise RuntimeError(f"无法启动 Chromium/Chrome。可用 --browser 指定本机浏览器路径。详情：{exc}") from exc
        page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]}, device_scale_factor=scale)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(f"console:{message.text}") if message.type == "error" else None)
        response = page.goto(html_file.as_uri(), wait_until="load", timeout=30000)
        page.evaluate("document.fonts.ready")
        page.add_style_tag(content="""html,body{height:auto!important;min-height:0!important;overflow:visible!important}
          .workspace{height:auto!important;min-height:0!important;flex:0 0 auto!important;overflow:visible!important}
          #canvas{min-height:0!important}#layout-meta,#layout-notice,#module-details{visibility:hidden!important}""")
        if omit_drill_icons:
            page.evaluate("""() => { const svg=document.querySelector('#canvas svg');
              if(svg?.classList.contains('architecture-diagram')) svg.querySelectorAll('.drill-icon').forEach(icon=>icon.remove()); }""")
        page.locator("#canvas svg").screenshot(path=str(png_file), animations="disabled", scale="device")
        dom = page.evaluate("""() => {
          const svg=document.querySelector('#canvas svg');
          if(!svg) return {svg:false, nodeCount:0, textOverflow:[], viewBox:null};
          const overflow=[];
          for(const node of svg.querySelectorAll('.node')){
            const card=node.querySelector('.node-card');if(!card)continue;
            const r={x:0,y:0,w:Number(card.getAttribute('width')),h:Number(card.getAttribute('height'))};
            for(const t of node.querySelectorAll('text')){const b=t.getBBox();if(b.x<0||b.x+b.width>r.w||b.y<0||b.y>r.h)overflow.push(node.dataset.node)}
          }
          const rect=svg.getBoundingClientRect(),workspace=document.querySelector('.workspace');
          return {svg:true,nodeCount:svg.querySelectorAll('.node').length,drillIconCount:svg.querySelectorAll('.drill-icon').length,textOverflow:[...new Set(overflow)],viewBox:svg.getAttribute('viewBox'),
            svgClientRect:{x:rect.x,y:rect.y,width:rect.width,height:rect.height},
            viewport:{width:innerWidth,height:innerHeight,documentWidth:document.documentElement.scrollWidth,
              workspaceWidth:workspace.clientWidth,workspaceScrollWidth:workspace.scrollWidth},title:document.title};
        }""")
        browser.close()
    image_size = _verify_capture_size(png_file, dom, scale)
    result = {"html": str(html_file), "screenshot": str(png_file), "browser": executable or "Playwright 默认 Chromium",
              "url_scheme": "file", "http_status": response.status if response else None,
              "viewport": {"width": viewport[0], "height": viewport[1], "scale": scale},
              "page_errors": errors, "dom": dom, "screenshot_dimensions": image_size,
              "omitted_drill_icons": bool(omit_drill_icons and dom.get("drillIconCount") == 0)}
    return result


def write_capture_report(report: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
