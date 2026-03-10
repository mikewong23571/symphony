from __future__ import annotations

from datetime import UTC, datetime

import pytest
from symphony.agent_runner import (
    DEFAULT_FALLBACK_PROMPT,
    PromptTemplateError,
    PromptTemplateParseError,
    PromptTemplateRenderError,
    build_continuation_guidance,
    render_issue_prompt,
)
from symphony.tracker.models import Issue, IssueBlocker


def build_issue() -> Issue:
    return Issue(
        id="issue-1",
        identifier="SYM-123",
        title="Implement prompt rendering",
        description="Render workflow prompts strictly.",
        priority=2,
        state="Todo",
        branch_name="feature/sym-123",
        url="https://linear.app/acme/issue/SYM-123",
        labels=("backend", "urgent"),
        blocked_by=(IssueBlocker(id="issue-2", identifier="SYM-100", state="In Progress"),),
        created_at=datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 3, 2, 9, 30, tzinfo=UTC),
    )


def test_render_issue_prompt_renders_issue_fields_with_null_attempt() -> None:
    rendered = render_issue_prompt(
        "Issue {{ issue.identifier }}: {{ issue.title }} / attempt={{ attempt }}",
        build_issue(),
    )

    assert rendered == "Issue SYM-123: Implement prompt rendering / attempt=None"


def test_render_issue_prompt_supports_nested_iteration_and_retry_attempt() -> None:
    rendered = render_issue_prompt(
        (
            "{% for label in issue.labels %}[{{ label }}]{% endfor %} "
            "{% for blocker in issue.blocked_by %}"
            "{{ blocker.identifier }}:{{ blocker.state }}"
            "{% endfor %} "
            "attempt={{ attempt }}"
        ),
        build_issue(),
        attempt=3,
    )

    assert rendered == "[backend][urgent] SYM-100:In Progress attempt=3"


def test_render_issue_prompt_uses_fallback_for_empty_template() -> None:
    assert render_issue_prompt("   ", build_issue()) == DEFAULT_FALLBACK_PROMPT


def test_render_issue_prompt_rejects_invalid_template_syntax() -> None:
    with pytest.raises(PromptTemplateParseError, match="could not be parsed") as exc_info:
        render_issue_prompt("{% if issue.identifier %}", build_issue())

    assert isinstance(exc_info.value, PromptTemplateError)
    assert exc_info.value.code == "template_parse_error"


def test_render_issue_prompt_rejects_unknown_variables() -> None:
    with pytest.raises(PromptTemplateRenderError, match="could not be rendered") as exc_info:
        render_issue_prompt("{{ issue.missing_field }}", build_issue())

    assert isinstance(exc_info.value, PromptTemplateError)
    assert exc_info.value.code == "template_render_error"


def test_render_issue_prompt_rejects_unknown_filters() -> None:
    with pytest.raises(PromptTemplateParseError, match="could not be parsed") as exc_info:
        render_issue_prompt("{{ issue.identifier | missing_filter }}", build_issue())

    assert isinstance(exc_info.value, PromptTemplateError)
    assert exc_info.value.code == "template_parse_error"


def test_build_continuation_guidance_is_continuation_only() -> None:
    guidance = build_continuation_guidance(
        build_issue(),
        attempt=2,
    )

    assert "SYM-123" in guidance
    assert "Attempt 2." in guidance
    assert "Do not repeat the original task prompt." in guidance
    assert "Implement prompt rendering" not in guidance
