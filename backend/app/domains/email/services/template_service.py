"""Jinja2-based email template renderer."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

# Required shared variables every template expects
_SHARED_VARS = ("subject", "frontend_base_url", "org_name")


def render_email_template(template_name: str, context: dict[str, object]) -> str:
    """Render a named template with the given context dict.

    Missing optional variables silently resolve to empty string via Jinja2 Undefined.
    Raises jinja2.TemplateNotFound if the template does not exist.
    """
    template = _env.get_template(template_name)
    return template.render(**context)
