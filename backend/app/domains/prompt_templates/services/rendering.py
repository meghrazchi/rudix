from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

VARIABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PLACEHOLDER_PATTERN = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")


class PromptTemplateValidationError(ValueError):
    pass


def extract_template_variables(content: str) -> set[str]:
    return set(PLACEHOLDER_PATTERN.findall(content))


def render_prompt_template(content: str, context: Mapping[str, Any]) -> str:
    missing: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        value = context.get(name)
        if value is None:
            missing.add(name)
            return ""
        if isinstance(value, str):
            return value
        return str(value)

    rendered = PLACEHOLDER_PATTERN.sub(replace, content)
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise PromptTemplateValidationError(f"Missing template variables: {missing_list}")
    return rendered


def validate_variable_names(variable_names: set[str]) -> None:
    for name in sorted(variable_names):
        if not VARIABLE_NAME_PATTERN.fullmatch(name):
            raise PromptTemplateValidationError(
                f"Invalid variable name '{name}'. Use letters, numbers, and underscores."
            )


def build_schema_from_variables(variables: list[dict[str, Any]]) -> dict[str, Any]:
    properties: dict[str, dict[str, str]] = {}
    required: list[str] = []
    for variable in variables:
        name = str(variable.get("name") or "").strip()
        if not name:
            continue
        properties[name] = {"type": "string"}
        if bool(variable.get("required", True)):
            required.append(name)
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def validate_template_definition(
    *,
    content: str,
    variables: list[dict[str, Any]],
    variable_schema: Mapping[str, Any],
    preview_context: Mapping[str, Any],
) -> None:
    stripped = content.strip()
    if not stripped:
        raise PromptTemplateValidationError("Prompt content must not be blank")

    declared_names = {str(variable.get("name") or "").strip() for variable in variables}
    if "" in declared_names:
        raise PromptTemplateValidationError("Variable names must not be blank")
    validate_variable_names(declared_names)

    placeholders = extract_template_variables(content)
    validate_variable_names(placeholders)
    undeclared = placeholders.difference(declared_names)
    if undeclared:
        missing = ", ".join(sorted(undeclared))
        raise PromptTemplateValidationError(f"Template variables are not declared: {missing}")

    schema_type = variable_schema.get("type")
    if schema_type is not None and schema_type != "object":
        raise PromptTemplateValidationError("Variable schema must be an object schema")

    schema_properties = variable_schema.get("properties", {})
    if schema_properties is not None and not isinstance(schema_properties, Mapping):
        raise PromptTemplateValidationError("Variable schema properties must be an object")
    if isinstance(schema_properties, Mapping):
        unknown_schema_keys = {str(key) for key in schema_properties.keys()}.difference(
            declared_names
        )
        if unknown_schema_keys:
            unknown = ", ".join(sorted(unknown_schema_keys))
            raise PromptTemplateValidationError(
                f"Variable schema references undeclared variables: {unknown}"
            )

    schema_required = variable_schema.get("required", [])
    if schema_required is not None:
        if not isinstance(schema_required, list):
            raise PromptTemplateValidationError("Variable schema required must be a list")
        unknown_required = {str(key) for key in schema_required}.difference(declared_names)
        if unknown_required:
            unknown = ", ".join(sorted(unknown_required))
            raise PromptTemplateValidationError(
                f"Variable schema requires undeclared variables: {unknown}"
            )

    default_context: dict[str, Any] = {}
    for variable in variables:
        name = str(variable["name"])
        if name in preview_context:
            default_context[name] = preview_context[name]
        elif "default" in variable and variable.get("default") is not None:
            default_context[name] = variable["default"]

    missing_preview = placeholders.difference(default_context.keys())
    if missing_preview:
        missing = ", ".join(sorted(missing_preview))
        raise PromptTemplateValidationError(
            f"Preview context is missing template variables: {missing}"
        )

    render_prompt_template(content, default_context)
