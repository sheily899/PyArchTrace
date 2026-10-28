from copy import deepcopy

from architecture_diagram.models import DiagramValidationError, validate_diagram


def test_valid_diagram_passes(simple_diagram):
    assert validate_diagram(simple_diagram) == []


def test_dangling_edge_is_rejected(simple_diagram):
    broken = deepcopy(simple_diagram)
    broken["edges"].append({"id": "bad", "from": "web", "to": "missing", "label": "错误关系", "kind": "call"})
    errors = validate_diagram(broken)
    assert any("不存在" in item for item in errors)


def test_rendered_labels_must_be_chinese_business_language(simple_diagram):
    broken = deepcopy(simple_diagram)
    broken["nodes"][1]["title"] = "IntentRecognizer"
    errors = validate_diagram(broken)
    assert any("英文" in item for item in errors)


def test_layer_assignment_is_mandatory(simple_diagram):
    broken = deepcopy(simple_diagram)
    broken["nodes"][0]["layer"] = "missing"
    errors = validate_diagram(broken)
    assert any("层" in item for item in errors)


def test_column_is_semantic_nonnegative_integer_not_coordinate(simple_diagram):
    simple_diagram["nodes"][0]["column"] = 2
    assert validate_diagram(simple_diagram) == []
    simple_diagram["nodes"][0]["column"] = -1
    assert any("column 必须是非负整数" in error for error in validate_diagram(simple_diagram))
    simple_diagram["nodes"][0]["column"] = 1.5
    assert any("column 必须是非负整数" in error for error in validate_diagram(simple_diagram))
