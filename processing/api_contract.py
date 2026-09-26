"""Validate HTTP documents against the checked-in OpenAPI source of truth."""

from functools import lru_cache
from pathlib import Path

import yaml
from jsonschema import FormatChecker
from jsonschema.exceptions import ValidationError

from processing.contracts import ContractValidator, _finite_tree


@lru_cache(maxsize=1)
def specification() -> dict:
    return yaml.safe_load((Path(__file__).resolve().parents[1] / "docs/openapi.yaml").read_text())


def validate_schema(name: str, data: dict) -> None:
    _finite_tree(data)
    schema = {**specification(), "$ref": f"#/components/schemas/{name}"}
    try:
        ContractValidator(schema, format_checker=FormatChecker()).validate(data)
    except (ValidationError, RecursionError) as exc:
        raise ValueError(f"Invalid {name}") from exc
