import json
from argparse import Namespace

from architecture_diagram.cli import _cmd_capture, _cmd_render, build_parser


def test_architecture_render_without_confirmation_does_not_create_output(tmp_path):
    diagram = {
        "schemaVersion": 1, "id": "main", "title": "主图", "type": "architecture", "direction": "TB",
        "layers": [{"id": "a", "name": "接入层"}],
        "nodes": [{"id": "n", "layer": "a", "title": "消息入口", "desc": "接收消息"}],
        "edges": [], "showEdgeLabels": False,
    }
    diagram_path = tmp_path / "diagram.json"
    output_dir = tmp_path / "must-not-exist"
    diagram_path.write_text(json.dumps(diagram), encoding="utf-8")
    args = Namespace(diagram=str(diagram_path), output_dir=str(output_dir), capture=False,
                     layout_backend="builtin", browser=None, viewport_width=1440,
                     viewport_height=1000, scale=2, analysis=None, approval=None, source_root=None)

    assert _cmd_render(args) == 2
    assert not output_dir.exists()


def test_parser_exposes_review_and_explicit_approval_commands():
    parser = build_parser()
    review = parser.parse_args(["review-structure", "analysis.json", "diagram.json", "--facts", "facts.json", "-o", "review.json"])
    approve = parser.parse_args(["approve-structure", "analysis.json", "diagram.json", "--facts", "facts.json", "--review", "review.json", "--confirmation", "确认", "-o", "approval.json"])
    assert review.command == "review-structure"
    assert approve.command == "approve-structure"


def test_architecture_html_cannot_be_screenshotted_through_generic_capture(tmp_path):
    html = tmp_path / "arch.html"
    png = tmp_path / "must-not-exist.png"
    html.write_text('<body class="architecture-only"></body>', encoding="utf-8")
    args = Namespace(html=str(html), png=str(png), report=None, browser=None,
                     viewport_width=1440, viewport_height=1000, scale=2,
                     analysis=None, diagram=None, facts=None, review=None, approval=None, source_root=None)

    assert _cmd_capture(args) == 2
    assert not png.exists()

