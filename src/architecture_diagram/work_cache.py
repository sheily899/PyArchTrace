"""Opt-in, content-addressed reuse for diagram layouts and unchanged audits."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable

from .versioning import LAYOUT_ALGORITHM_VERSION


_LAYOUT_CODE = ("layout.py", "elkjs_backend.py", "scripts/layout_elk.mjs")
_VALIDATION_CODE = ("models.py",)
_AUDIT_CODE = ("approval.py", "analysis_audit.py", "details.py", "layout.py",
               "models.py", "quality.py", "render.py")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


class WorkCache:
    """Cache layouts and complete structure audits; callers opt in explicitly."""

    def __init__(self, directory: str | Path, *, layout_version: str = LAYOUT_ALGORITHM_VERSION):
        self.directory = Path(directory)
        self.layout_version = layout_version
        self._stats = {
            "layoutRequests": 0, "layoutCacheHits": 0, "layoutComputations": 0,
            "validationRequests": 0, "validationCacheHits": 0, "validationComputations": 0,
            "auditCacheHits": 0, "auditComputations": 0,
        }

    def _code_digest(self, filenames: tuple[str, ...]) -> dict[str, str]:
        package = Path(__file__).parent
        result = {}
        for name in (*filenames, "work_cache.py"):
            path = package / name
            try:
                result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                result[name] = "missing"
        return result

    @staticmethod
    def _backend_fingerprint(backend: str) -> dict[str, Any]:
        if backend not in {"auto", "elkjs"}:
            return {"requested": backend}
        from . import elkjs_backend

        node = elkjs_backend._node_path()
        module = elkjs_backend._elk_module_path()
        module_stat = None
        if module:
            try:
                stat = Path(module).stat()
                module_stat = {"size": stat.st_size, "mtimeNs": stat.st_mtime_ns}
            except OSError:
                module_stat = "unavailable"
        return {"requested": backend, "node": node, "elkModule": module,
                "elkAvailable": elkjs_backend.available(), "elkModuleStat": module_stat}

    def _cache_path(self, kind: str, key: str) -> Path:
        return self.directory / f"{kind}-{key}.json"

    def _read(self, kind: str, key: str) -> Any | None:
        path = self._cache_path(kind, key)
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(entry, dict) or entry.get("key") != key or "value" not in entry:
            return None
        return entry["value"]

    def _write(self, kind: str, key: str, value: Any) -> None:
        target = self._cache_path(kind, key)
        temporary: Path | None = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.directory,
                                             prefix=f".{kind}-", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump({"key": key, "value": value}, handle, ensure_ascii=False,
                          sort_keys=True, separators=(",", ":"))
            os.replace(temporary, target)
        except OSError:
            # Caching is an optimization. A read-only or unavailable cache must
            # not change whether a diagram can be reviewed or rendered.
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def layout(self, diagram: dict, *, backend: str = "auto", hardcoded_ports: bool = False) -> dict:
        key = _hash({
            "ir": diagram,
            "layoutVersion": self.layout_version,
            "parameters": {"backend": self._backend_fingerprint(backend),
                           "hardcodedPorts": hardcoded_ports},
            "implementation": self._code_digest(_LAYOUT_CODE),
        })
        self._stats["layoutRequests"] += 1
        cached = self._read("layout", key)
        if isinstance(cached, dict):
            self._stats["layoutCacheHits"] += 1
            return cached

        from .layout import layout_diagram

        self._stats["layoutComputations"] += 1
        result = layout_diagram(diagram, backend=backend, hardcoded_ports=hardcoded_ports)
        self._write("layout", key, result)
        return result

    def validate(self, diagram: dict, validator: Callable[[Any], list[str]]) -> list[str]:
        key = _hash({"ir": diagram, "implementation": self._code_digest(_VALIDATION_CODE)})
        self._stats["validationRequests"] += 1
        cached = self._read("validation", key)
        if isinstance(cached, list) and all(isinstance(item, str) for item in cached):
            self._stats["validationCacheHits"] += 1
            return cached
        self._stats["validationComputations"] += 1
        result = validator(diagram)
        self._write("validation", key, result)
        return result

    def audit_key(self, analysis: dict, diagram: dict, facts: dict | None,
                  source_root: str | Path | None, backend: str) -> str:
        evidence_fingerprint = _evidence_fingerprint((analysis, diagram), source_root)
        return _hash({
            "analysis": analysis,
            "diagram": diagram,
            "facts": facts,
            "sourceRoot": str(Path(source_root).resolve()) if source_root is not None else None,
            "sourceEvidence": evidence_fingerprint,
            "backend": backend,
            "layoutVersion": self.layout_version,
            "implementation": self._code_digest(_AUDIT_CODE),
        })

    def get_audit(self, key: str) -> dict | None:
        result = self._read("audit", key)
        if isinstance(result, dict):
            self._stats["auditCacheHits"] += 1
            return result
        return None

    def set_audit(self, key: str, report: dict) -> None:
        self._stats["auditComputations"] += 1
        self._write("audit", key, report)

    def stats(self) -> dict[str, int]:
        return dict(self._stats)

    def with_stats(self, report: dict) -> dict:
        copied = json.loads(json.dumps(report, ensure_ascii=False))
        copied["workCache"] = {"directory": str(self.directory), **self.stats()}
        return copied


def _evidence_fingerprint(objects: tuple[dict, ...], source_root: str | Path | None) -> list[dict[str, str]]:
    if source_root is None:
        return []
    root = Path(source_root).resolve()
    referenced: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            evidence = value.get("evidence")
            if isinstance(evidence, list):
                for item in evidence:
                    if isinstance(item, dict) and isinstance(item.get("path"), str):
                        referenced.add(item["path"])
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for value in objects:
        visit(value)

    result = []
    for relative in sorted(referenced):
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
            digest = hashlib.sha256(candidate.read_bytes()).hexdigest() if candidate.is_file() else "missing"
        except (OSError, ValueError):
            digest = "unreadable-or-outside-root"
        result.append({"path": relative, "sha256": digest})
    return result
