import json
from pathlib import Path

from jsonschema import Draft202012Validator
from architecture_diagram.cli import _schema_path


def test_sample_matches_published_schema(simple_diagram):
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "schemas" / "diagram.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    errors = list(Draft202012Validator(schema).iter_errors(simple_diagram))
    assert errors == []


def test_cli_can_find_schema_in_source_checkout():
    assert _schema_path().is_file()


def test_analysis_schema_is_valid_json_schema():
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "schemas" / "analysis.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
