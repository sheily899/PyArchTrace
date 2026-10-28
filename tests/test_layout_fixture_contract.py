from __future__ import annotations

import json
from pathlib import Path

import pytest

from architecture_diagram.layout import layout_diagram
from architecture_diagram.models import validate_diagram
from architecture_diagram.quality import quality_report
from layout_fixture_support import _normalize_fixture


FIXTURES = Path(__file__).parent / "layout_fixtures"


def _load_cases():
    cases = []
    for path in sorted(FIXTURES.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        diagram, target = _normalize_fixture(raw)
        cases.append((raw, diagram, target))
    return cases


@pytest.mark.parametrize(
    "raw,diagram,target",
    _load_cases(),
    ids=lambda item: item.get("caseId", "fixture") if isinstance(item, dict) else None,
)
def test_layout_fixture_contract(raw: dict, diagram: dict, target: dict):
    expected_outcome = raw.get("target", {}).get("expectedOutcome", "valid")
    errors = validate_diagram(diagram)

    if expected_outcome == "invalid":
        assert errors, f"{raw['caseId']} 应被当前契约拦截"
        return

    assert not errors, f"{raw['caseId']}: {errors}"
    is_flow = diagram.get("type") == "flow"
    layout = layout_diagram(diagram, backend="builtin", hardcoded_ports=is_flow)
    audit = quality_report(diagram, layout, hardcoded_ports=is_flow)
    assert audit["passed"], f"{raw['caseId']}: {audit['issues']}"
    if diagram.get("type") == "architecture":
        assert diagram["layout"]["contractVersion"] == 2
        assert layout["template"] == target["expectedTemplate"]

