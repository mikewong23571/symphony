from __future__ import annotations

from dataclasses import asdict

from jinja2 import Environment, StrictUndefined
from jinja2.exceptions import TemplateAssertionError, TemplateError, TemplateSyntaxError

from symphony.tracker.models import Issue

DEFAULT_FALLBACK_PROMPT = "You are working on an issue from Linear."


class PromptTemplateError(Exception):
    code = "template_parse_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def render_issue_prompt(
    prompt_template: str,
    issue: Issue,
    *,
    attempt: int | None = None,
) -> str:
    if not prompt_template.strip():
        return DEFAULT_FALLBACK_PROMPT

    environment = Environment(undefined=StrictUndefined, autoescape=False)

    try:
        template = environment.from_string(prompt_template)
        rendered = template.render(issue=asdict(issue), attempt=attempt)
    except (TemplateAssertionError, TemplateSyntaxError, TemplateError) as exc:
        raise PromptTemplateError("Workflow prompt template could not be rendered.") from exc

    return rendered.strip()


def build_continuation_guidance(issue: Issue, *, attempt: int | None = None) -> str:
    attempt_suffix = "" if attempt is None else f" Attempt {attempt}."
    return (
        f"Continue working in the existing thread for issue {issue.identifier}."
        f"{attempt_suffix} Do not repeat the original task prompt. Resume from the latest thread"
        " state and continue toward completion."
    )
