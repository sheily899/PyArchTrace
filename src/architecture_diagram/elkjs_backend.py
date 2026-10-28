"""可选 ELKJS layered 适配器；缺失时由调用方回退到内置布局。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def _node_path() -> str | None:
    node = shutil.which("node")
    if node:
        return node
    for candidate in (
        Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe",
        Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node",
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def _elk_module_path() -> str | None:
    explicit = os.environ.get("ARCHITECTURE_DIAGRAM_ELK_MODULE")
    candidates = [Path(explicit)] if explicit else []
    candidates.extend([
        Path(__file__).resolve().parents[2] / "node_modules/elkjs/lib/elk.bundled.js",
        Path.cwd() / "node_modules/elkjs/lib/elk.bundled.js",
    ])
    return str(next((path.resolve() for path in candidates if path.is_file()), "")) or None


def available() -> bool:
    return bool(_node_path() and _elk_module_path())


def layout_with_elkjs(diagram: dict, sizes: dict[str, dict]) -> dict | None:
    node, module = _node_path(), _elk_module_path()
    if not node or not module:
        return None
    script = Path(__file__).parent / "scripts" / "layout_elk.mjs"
    request = {
        "direction": diagram.get("direction", "LR"),
        "nodes": [{"id": item["id"], "width": sizes[item["id"]]["width"], "height": sizes[item["id"]]["height"]}
                  for item in diagram["nodes"]],
        "edges": [{"id": item["id"], "from": item["from"], "to": item["to"]} for item in diagram["edges"]],
    }
    result = subprocess.run([node, str(script), module], input=json.dumps(request), text=True,
                            capture_output=True, timeout=45)
    if result.returncode:
        raise RuntimeError(f"ELKJS 布局失败：{result.stderr.strip()}")
    graph = json.loads(result.stdout)
    children = graph.get("children", [])
    axis = "x" if diagram.get("direction", "LR") == "LR" else "y"
    positions_raw = {item["id"]: item for item in children}
    layer_values = sorted({round(float(item[axis]) / 4) * 4 for item in children})
    supplied = diagram.get("layers", [])
    layer_ids = [layer["id"] for layer in supplied]
    layer_names = {layer["id"]: layer["name"] for layer in supplied}
    node_layers: dict[str, str] = {}
    for item in children:
        coordinate = round(float(item[axis]) / 4) * 4
        rank = layer_values.index(coordinate)
        layer_id = layer_ids[rank] if rank < len(layer_ids) else f"step-{rank + 1}"
        node_layers[item["id"]] = layer_id
    positions = []
    grouped: dict[str, list[dict]] = {}
    for source in diagram["nodes"]:
        placed = positions_raw[source["id"]]
        size = sizes[source["id"]]
        item = {"id": source["id"], "layer": node_layers[source["id"]],
                "x": float(placed.get("x", 0)), "y": float(placed.get("y", 0)),
                "width": size["width"], "height": size["height"],
                "title_lines": size["title_lines"], "desc_lines": size["desc_lines"]}
        positions.append(item)
        grouped.setdefault(item["layer"], []).append(item)
    layers = []
    for rank, layer_id in enumerate(sorted(grouped, key=lambda key: min(item[axis] for item in grouped[key]))):
        members = grouped[layer_id]
        if axis == "x":
            x = min(item["x"] for item in members) - 22
            y = min(item["y"] for item in members) - 24
            width = max(item["x"] + item["width"] for item in members) - x + 22
            height = max(210, max(item["y"] + item["height"] for item in members) - y + 24)
        else:
            x = min(item["x"] for item in members) - 22
            y = min(item["y"] for item in members) - 24
            width = max(900, max(item["x"] + item["width"] for item in members) - x + 22)
            height = max(item["y"] + item["height"] for item in members) - y + 24
        layers.append({"id": layer_id, "name": layer_names.get(layer_id, f"第{rank + 1}步"),
                       "x": x, "y": y, "width": width, "height": height, "crossCutting": False})
    edge_output = []
    edges_by_id = {edge["id"]: edge for edge in diagram["edges"]}
    for placed in graph.get("edges", []):
        source = edges_by_id[placed["id"]]
        sections = placed.get("sections", [])
        section = sections[0] if sections else {}
        points = []
        if section.get("startPoint"):
            points.append(section["startPoint"])
        points.extend(section.get("bendPoints", []))
        if section.get("endPoint"):
            points.append(section["endPoint"])
        points = [{"x": float(point["x"]), "y": float(point["y"])} for point in points]
        edge_output.append({"id": source["id"], "from": source["from"], "to": source["to"],
                            "label": source["label"], "kind": source.get("kind", "other"),
                            "main": bool(source.get("main")), "async": bool(source.get("async")),
                            "points": points, "bends": max(0, len(points) - 2)})
    width = max((item["x"] + item["width"] for item in positions), default=900) + 36
    height = max((item["y"] + item["height"] for item in positions), default=300) + 56
    return {"width": width, "height": height, "nodes": positions, "layers": layers, "edges": edge_output}
