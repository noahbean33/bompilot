"""
Email template renderer.

Templates are plain-text files stored in the templates/ subdirectory.
Each template must start with a subject line:

    Subject: Your email subject here

    Email body follows...
    Supports {placeholder} formatting via str.format().

Usage:
    subject, body = render_template("trial_activated", trial_end_date="2026-06-30")
"""

import pathlib
from typing import Tuple

_TEMPLATES_DIR = pathlib.Path(__file__).parent / "templates"


def render_template(name: str, **context) -> Tuple[str, str]:
    """
    Load a template by name and render it with the given context.

    Args:
        name: Template file name without the .txt extension.
        **context: Keyword arguments passed to str.format() on the body.

    Returns:
        A (subject, body) tuple.

    Raises:
        FileNotFoundError: If the template file does not exist.
        ValueError: If the template is missing a Subject line.
        KeyError: If a placeholder in the template is not provided in context.
    """
    path = _TEMPLATES_DIR / f"{name}.txt"
    content = path.read_text(encoding="utf-8")

    lines = content.splitlines()
    if not lines or not lines[0].startswith("Subject: "):
        raise ValueError(f"Template '{name}' is missing a 'Subject: ...' line")

    subject = lines[0][len("Subject: "):].strip()
    body_template = "\n".join(lines[1:]).strip()

    try:
        body = body_template.format(**context)
    except KeyError as exc:
        raise KeyError(
            f"Missing template variable {exc} for template '{name}'"
        ) from exc

    return subject, body
