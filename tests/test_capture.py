import struct
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from architecture_diagram.capture import _browser_path, _node_playwright, _png_dimensions, capture_html
from architecture_diagram.layout import layout_diagram
from architecture_diagram.render import render_html


def test_png_dimensions_read_intrinsic_raster_size():
    png_header = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 2910, 2294)

    assert _png_dimensions(png_header) == (2910, 2294)


def test_capture_html_includes_svg_content_beyond_scroll_viewport(tmp_path: Path):
    if not _node_playwright() or not _browser_path(None):
        pytest.skip("需要本机 Node Playwright 与 Chromium/Chrome")
    html_path = tmp_path / "tall-canvas.html"
    png_path = tmp_path / "tall-canvas.png"
    html_path.write_text("""<!doctype html><html><head><style>
      *{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;overflow:hidden}
      body{display:flex;flex-direction:column}header{height:40px;flex:0 0 40px}
      .workspace{height:calc(100vh - 40px);flex:1;overflow:auto}#canvas{width:100%;min-height:100%;display:flex}
      #canvas svg{display:block;width:100%;height:auto;max-width:1600px}
      </style></head><body><header>工具栏</header><main class="workspace"><div id="canvas">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 1200" width="800" height="1200">
        <rect width="800" height="1200" fill="#ffffff"/><rect x="0" y="1050" width="800" height="150" fill="#ef4444"/>
      </svg></div></main></body></html>""", encoding="utf-8")

    report = capture_html(html_path, png_path, viewport=(800, 400), scale=1)

    assert report["screenshot_dimensions"]["width"] == 800
    assert report["screenshot_dimensions"]["height"] == 1200
    assert report["dom"]["svgClientRect"]["height"] == 1200
    with Image.open(png_path).convert("RGB") as image:
        red = image.getpixel((400, 1150))
    assert red[0] > 220 and red[1] < 100 and red[2] < 100


def test_capture_can_omit_architecture_drill_icons_without_changing_interactive_html(tmp_path: Path, simple_diagram):
    if not _node_playwright() or not _browser_path(None):
        pytest.skip("需要本机 Node Playwright 与 Chromium/Chrome")
    simple_diagram["nodes"][0]["drilldown"] = "detail"
    html_path = tmp_path / "architecture.html"
    png_path = tmp_path / "architecture.png"
    html_path.write_text(render_html(simple_diagram, layout_diagram(simple_diagram)), encoding="utf-8")

    assert 'class="drill-icon"' in html_path.read_text(encoding="utf-8")
    report = capture_html(html_path, png_path, viewport=(1200, 900), scale=1, omit_drill_icons=True)

    assert report["omitted_drill_icons"] is True
    assert report["dom"]["drillIconCount"] == 0
    assert png_path.is_file()


def test_browser_svg_and_png_exports_hide_architecture_drill_icons(tmp_path: Path, simple_diagram):
    runtime = _node_playwright()
    browser = _browser_path(None)
    if not runtime or not browser:
        pytest.skip("需要本机 Node Playwright 与 Chromium/Chrome")
    simple_diagram["nodes"][0]["drilldown"] = "detail"
    html_path = tmp_path / "architecture.html"
    svg_path = tmp_path / "exported.svg"
    png_path = tmp_path / "exported.png"
    html_path.write_text(render_html(simple_diagram, layout_diagram(simple_diagram)), encoding="utf-8")
    helper = Path(__file__).with_name("browser_export_icons.mjs")

    result = subprocess.run([runtime[0], str(helper), str(html_path), str(svg_path), str(png_path), runtime[1], browser],
                            capture_output=True, text=True, encoding="utf-8", timeout=60)

    assert result.returncode == 0, result.stderr or result.stdout
