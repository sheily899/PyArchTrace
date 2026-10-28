import json
from pathlib import Path

from architecture_diagram import layout, render
from architecture_diagram.approval import inspect_structure
from architecture_diagram.work_cache import WorkCache


def _child_flow():
    return {
        "schemaVersion": 1,
        "id": "detail",
        "title": "模块细节",
        "type": "flow",
        "direction": "TB",
        "layers": [{"id": "step", "name": "处理步骤"}],
        "nodes": [{"id": "detail-node", "layer": "step", "title": "执行处理", "desc": "处理输入"}],
        "edges": [],
        "subDiagrams": [],
    }


def test_layout_cache_reuses_across_instances_and_invalidates_for_ir_and_version(
    tmp_path, simple_diagram, monkeypatch
):
    calls = 0
    actual = layout.layout_diagram

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return actual(*args, **kwargs)

    monkeypatch.setattr(layout, "layout_diagram", counted)
    first_cache = WorkCache(tmp_path / "cache", layout_version="test-layout-1")
    first = first_cache.layout(simple_diagram, backend="builtin")
    second_cache = WorkCache(tmp_path / "cache", layout_version="test-layout-1")
    second = second_cache.layout(simple_diagram, backend="builtin")

    assert first == second
    assert calls == 1
    assert second_cache.stats()["layoutCacheHits"] == 1

    changed = json.loads(json.dumps(simple_diagram))
    changed["nodes"][0]["desc"] = "处理新请求"
    second_cache.layout(changed, backend="builtin")
    WorkCache(tmp_path / "cache", layout_version="test-layout-2").layout(
        simple_diagram, backend="builtin"
    )
    assert calls == 3


def test_validation_cache_reuses_only_identical_diagram(tmp_path, simple_diagram):
    cache = WorkCache(tmp_path / "cache")
    calls = 0

    def validator(diagram):
        nonlocal calls
        calls += 1
        return ["invalid"] if diagram.get("title") == "invalid" else []

    assert cache.validate(simple_diagram, validator) == []
    assert cache.validate(simple_diagram, validator) == []
    changed = {**simple_diagram, "title": "invalid"}
    assert cache.validate(changed, validator) == ["invalid"]
    assert calls == 2
    assert cache.stats()["validationCacheHits"] == 1


def test_audit_cache_invalidates_when_evidence_source_changes(tmp_path, simple_diagram):
    source_root = tmp_path / "source"
    (source_root / "src").mkdir(parents=True)
    for node in simple_diagram["nodes"]:
        path = source_root / node["evidence"][0]["path"]
        path.write_text("initial evidence\n", encoding="utf-8")
    cache = WorkCache(tmp_path / "cache")
    analysis, facts = {}, {}

    first_key = cache.audit_key(analysis, simple_diagram, facts, source_root, "builtin")
    cache.set_audit(first_key, {"passed": False, "analysisAudit": {"errors": ["expected test fixture"]}})
    assert cache.get_audit(first_key)["analysisAudit"]["errors"] == ["expected test fixture"]

    (source_root / "src" / "web.py").write_text("changed evidence\n", encoding="utf-8")
    second_key = cache.audit_key(analysis, simple_diagram, facts, source_root, "builtin")
    assert second_key != first_key
    assert cache.get_audit(second_key) is None


def test_structure_audit_reuses_complete_report_and_keeps_checks(
    tmp_path, simple_diagram, monkeypatch
):
    calls = []
    actual_layout = layout.layout_diagram

    def counted_layout(diagram, **kwargs):
        calls.append(diagram["id"])
        return actual_layout(diagram, **kwargs)

    monkeypatch.setattr(layout, "layout_diagram", counted_layout)
    source_root = tmp_path / "source"
    child = _child_flow()
    child["nodes"][0]["evidence"] = [{"path": "src/detail.py", "line": 1}]
    simple_diagram["subDiagrams"] = [child]
    simple_diagram["nodes"][0]["drilldown"] = child["id"]
    nodes = [*simple_diagram["nodes"], *child["nodes"]]
    for node in nodes:
        path = source_root / node["evidence"][0]["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("evidence\n", encoding="utf-8")
    cache = WorkCache(tmp_path / "cache")
    analysis, facts = {}, {}

    first = inspect_structure(analysis, simple_diagram, source_root=source_root,
                              backend="builtin", facts=facts, work_cache=cache)
    second = inspect_structure(analysis, simple_diagram, source_root=source_root,
                               backend="builtin", facts=facts, work_cache=cache)

    assert {key: value for key, value in first.items() if key != "workCache"} == {
        key: value for key, value in second.items() if key != "workCache"
    }
    assert first["workCache"]["layoutComputations"] == 2
    assert second["workCache"]["auditCacheHits"] == 1
    assert second["workCache"]["layoutComputations"] == 2

    root_layout = cache.layout(simple_diagram, backend="builtin")
    child_layout = cache.layout(child, backend="builtin", hardcoded_ports=True)
    monkeypatch.setattr(render, "layout_diagram",
                        lambda *args, **kwargs: (_ for _ in ()).throw(
                            AssertionError("HTML render must use precomputed child layouts")))
    render.render_html(simple_diagram, root_layout, backend="builtin",
                       precomputed_layouts={child["id"]: child_layout})
    assert cache.stats()["layoutComputations"] == 2
    assert calls == [simple_diagram["id"], child["id"]]


def test_render_html_uses_precomputed_subdiagram_layouts(tmp_path, simple_diagram, monkeypatch):
    child = _child_flow()
    simple_diagram["subDiagrams"] = [child]
    simple_diagram["nodes"][0]["drilldown"] = child["id"]
    root_layout = layout.layout_diagram(simple_diagram, backend="builtin")
    child_layout = layout.layout_diagram(child, backend="builtin")

    def unexpected_layout(*args, **kwargs):
        raise AssertionError("render_html must reuse supplied root and subdiagram layouts")

    monkeypatch.setattr(render, "layout_diagram", unexpected_layout)
    html = render.render_html(simple_diagram, root_layout, backend="builtin",
                              precomputed_layouts={child["id"]: child_layout})
    assert '"detail"' in html
    assert "执行处理" in html
