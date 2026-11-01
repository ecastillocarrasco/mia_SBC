"""Normalize tool arguments through their actual typed contract, without executing tools."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, TypeAdapter


def normalize_plan_arguments(
    model: type[BaseModel], arguments: dict[str, Any], message: str, today: date
) -> dict[str, Any]:
    normalized = normalize_arguments(model, arguments, partial=True)
    validator = getattr(model, "validate_intent_arguments", None)
    if callable(validator):
        validator(normalized, message, today)
    return normalized


def normalize_arguments(model: type[BaseModel], arguments: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    if arguments.keys() - model.model_fields.keys():
        raise ValueError("Campos no declarados en el contrato de la herramienta")
    if not partial or all(not field.is_required() or key in arguments for key, field in model.model_fields.items()):
        return model.model_validate(arguments).model_dump(mode="json", exclude_unset=partial)
    # A step can declare only its essential filters. Missing required execution
    # parameters remain required when the actual call is validated in full.
    normalized = {}
    for key, value in arguments.items():
        adapter = TypeAdapter(model.model_fields[key].rebuild_annotation())
        normalized[key] = adapter.dump_python(adapter.validate_python(value), mode="json")
    return normalized
