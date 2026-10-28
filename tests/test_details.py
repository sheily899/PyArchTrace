from architecture_diagram.details import enrich_diagram_details


def test_detail_dependency_technology_and_files_are_derived_from_evidence_and_facts():
    analysis = {
        "stageB": {"modules": [
            {"id": "router", "evidence": [{"path": "src/router.py", "line": 3, "claim": "分发请求"}]},
            {"id": "store", "evidence": [{"path": "src/store.py", "line": 2, "claim": "读取记录"}]},
        ]},
        "stageC": {"relations": [
            {"id": "r1", "from": "router", "to": "store", "kind": "function_call", "evidence": [{"path": "src/router.py", "line": 8, "claim": "读取记录"}]},
        ]},
    }
    facts = {"modules": [
        {"path": "src/router.py", "imports": [{"module": "redis.client", "line": 1}]},
        {"path": "src/store.py", "imports": [{"module": "sqlite3", "line": 1}]},
    ]}
    semantic = {"summary": "选择请求处理方式", "responsibilities": ["选择处理分支"], "inputs": ["用户请求"], "outputs": ["目标处理模块"]}
    diagram = {
        "id": "main", "type": "architecture", "nodes": [
            {"id": "router", "title": "请求路由", "evidence": analysis["stageB"]["modules"][0]["evidence"], "details": dict(semantic)},
            {"id": "store", "title": "记录存储", "evidence": analysis["stageB"]["modules"][1]["evidence"], "details": dict(semantic)},
        ],
        "edges": [{"id": "e1", "from": "router", "to": "store", "relationIds": ["r1"]}],
        "subDiagrams": [],
    }

    result = enrich_diagram_details(diagram, analysis, facts)
    router, store = result["nodes"]
    assert router["details"]["depends_on"] == ["store"]
    assert store["details"]["used_by"] == ["router"]
    assert router["details"]["key_files"] == ["src/router.py"]
    assert router["details"]["tech"] == ["redis"]
    assert router["details"]["confidence"]["evidence"] == ["src/router.py:3 分发请求"]


def test_details_fail_when_model_semantic_fields_are_missing():
    diagram = {"id": "main", "type": "architecture", "nodes": [{"id": "n", "details": {"summary": "职责"}}], "edges": []}
    try:
        enrich_diagram_details(diagram, {"stageB": {"modules": []}, "stageC": {"relations": []}}, {"modules": []})
    except ValueError as exc:
        assert "responsibilities" in str(exc)
    else:
        raise AssertionError("missing semantic details must fail")
