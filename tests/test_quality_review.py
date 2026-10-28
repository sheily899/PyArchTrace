from architecture_diagram.layout import layout_diagram
from architecture_diagram.quality import quality_report
from architecture_diagram.review import apply_review
from architecture_diagram.models import validate_diagram


def test_geometry_report_accepts_a_single_vertical_main_chain(simple_diagram):
    report = quality_report(simple_diagram, layout_diagram(simple_diagram))
    assert report["counts"]["diagonal_edges"] == 0
    assert report["counts"]["node_overlaps"] == 0


def test_review_adjustment_changes_spacing_and_preserves_schema(simple_diagram):
    revised, notes = apply_review(simple_diagram, {
        "verdict": "revise",
        "adjustments": [{"type": "increase_spacing", "axis": "x", "factor": 1.3}],
    })
    assert revised["layout"]["gapX"] > 36
    assert notes
    assert validate_diagram(revised) == []


def test_review_can_fix_chinese_module_text(simple_diagram):
    revised, _ = apply_review(simple_diagram, {
        "adjustments": [{"type": "edit_text", "nodeId": "router", "field": "title", "value": "需求分流"}],
    })
    assert revised["nodes"][1]["title"] == "需求分流"
    assert validate_diagram(revised) == []
