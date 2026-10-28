import pytest


@pytest.fixture
def simple_diagram():
    return {
        "schemaVersion": 1,
        "id": "demo",
        "title": "示例服务处理链路",
        "type": "architecture",
        "direction": "TB",
        "template": "A",
        "mainChain": ["web", "router", "store"],
        "layerFlows": [
            {"id": "flow-1", "fromLayer": "L1", "toLayer": "L2", "label": "接收请求", "evidence": [{"path": "src/web.py", "line": 1}]},
            {"id": "flow-2", "fromLayer": "L2", "toLayer": "L3", "label": "保存状态", "evidence": [{"path": "src/store.py", "line": 1}]},
        ],
        "layout": {"contractVersion": 2},
        "layers": [
            {"id": "L1", "name": "接入层", "standardType": "access", "evidence": [{"path": "src/web.py", "line": 1}]},
            {"id": "L2", "name": "业务层", "standardType": "business", "evidence": [{"path": "src/router.py", "line": 1}]},
            {"id": "L3", "name": "数据层", "standardType": "data", "evidence": [{"path": "src/store.py", "line": 1}]},
        ],
        "nodes": [
            {"id": "web", "layer": "L1", "title": "消息入口", "desc": "接收请求", "status": "implemented", "order": 1, "evidence": [{"path": "src/web.py", "line": 1}]},
            {"id": "router", "layer": "L2", "title": "意图分流", "desc": "识别需求", "status": "implemented", "order": 1, "evidence": [{"path": "src/router.py", "line": 1}]},
            {"id": "store", "layer": "L3", "title": "会话记录", "desc": "保存状态", "status": "implemented", "order": 1, "evidence": [{"path": "src/store.py", "line": 1}]},
        ],
        "edges": [],
        "subDiagrams": [],
    }
