from __future__ import annotations

import functools
import json
from html import escape
from urllib.parse import quote

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from symphony.observability.runtime import (
    RuntimeIssueNotFoundError,
    RuntimeSnapshotUnavailableError,
    get_runtime_issue_snapshot,
    get_runtime_snapshot,
    queue_runtime_refresh_request,
)
from symphony.tracker.write_contract import (
    TrackerCommentRequest,
    TrackerIssueNotFoundError,
    TrackerMutationError,
    TrackerPullRequestRequest,
    TrackerTransitionRequest,
    TrackerValidationError,
)
from symphony.tracker.write_service import (
    TrackerMutationService,
    build_tracker_mutation_service,
)
from symphony.workflow import (
    WorkflowConfigError,
    WorkflowError,
    build_service_config,
    load_workflow_definition,
    validate_dispatch_config,
)

ALLOWED_DASHBOARD_METHODS = "GET, HEAD"
ALLOWED_STATE_METHODS = "GET, HEAD"
ALLOWED_ISSUE_METHODS = "GET, HEAD"
ALLOWED_REFRESH_METHODS = "POST"
ALLOWED_TRACKER_MUTATION_METHODS = "POST"


def healthcheck(_request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok", "service": "symphony-api"})


@csrf_exempt
def runtime_dashboard(request: HttpRequest) -> HttpResponse:
    if request.method not in {"GET", "HEAD"}:
        response = _html_response(
            title="Method not allowed",
            body=f"<p>Method {escape(repr(request.method))} is not allowed for /.</p>",
            status=405,
        )
        response["Allow"] = ALLOWED_DASHBOARD_METHODS
        return response

    try:
        snapshot = get_runtime_snapshot()
    except RuntimeSnapshotUnavailableError as exc:
        return _html_response(
            title="Runtime snapshot unavailable",
            body=f"<p>{escape(str(exc))}</p>",
            status=503,
        )
    except TimeoutError as exc:
        return _html_response(
            title="Runtime snapshot timed out",
            body=f"<p>{escape(str(exc))}</p>",
            status=503,
        )

    running_rows = "".join(_render_running_row(entry) for entry in snapshot.get("running", []))
    retry_rows = "".join(_render_retry_row(entry) for entry in snapshot.get("retrying", []))
    counts = snapshot.get("counts", {})
    codex_totals = snapshot.get("codex_totals", {})
    body = "".join(
        [
            "<p>Read-only observability view backed by the orchestrator runtime snapshot.</p>",
            f"<p>Generated at: <code>{escape(str(snapshot.get('generated_at', '')))}</code></p>",
            "<ul>",
            f"<li>Running: {escape(str(counts.get('running', 0)))}</li>",
            f"<li>Retrying: {escape(str(counts.get('retrying', 0)))}</li>",
            f"<li>Total tokens: {escape(str(codex_totals.get('total_tokens', 0)))}</li>",
            f"<li>Seconds running: {escape(str(codex_totals.get('seconds_running', 0.0)))}</li>",
            "</ul>",
            '<p><a href="/api/v1/state">JSON state</a></p>',
            "<h2>Running</h2>",
            (
                "<table><thead><tr><th>Issue</th><th>State</th><th>Session</th><th>Last event</th>"
                "<th>Workspace</th></tr></thead><tbody>"
                f"{running_rows or '<tr><td colspan="5">No running issues.</td></tr>'}"
                "</tbody></table>"
            ),
            "<h2>Retrying</h2>",
            (
                "<table><thead><tr><th>Issue</th><th>Attempt</th><th>Due at</th><th>Error</th>"
                "<th>Workspace</th></tr></thead><tbody>"
                f"{retry_rows or '<tr><td colspan="5">No retry entries.</td></tr>'}"
                "</tbody></table>"
            ),
        ]
    )
    return _html_response(title="Symphony Runtime", body=body)


@csrf_exempt
def runtime_state(request: HttpRequest) -> JsonResponse:
    if request.method not in {"GET", "HEAD"}:
        response = _error_response(
            code="method_not_allowed",
            message=f"Method {request.method!r} is not allowed for /api/v1/state.",
            status=405,
        )
        response["Allow"] = ALLOWED_STATE_METHODS
        return response

    try:
        snapshot = get_runtime_snapshot()
    except RuntimeSnapshotUnavailableError as exc:
        return _error_response(code="unavailable", message=str(exc), status=503)
    except TimeoutError as exc:
        return _error_response(code="timeout", message=str(exc), status=503)

    return JsonResponse(snapshot)


@csrf_exempt
def runtime_issue(request: HttpRequest, issue_identifier: str) -> JsonResponse:
    if request.method not in {"GET", "HEAD"}:
        response = _error_response(
            code="method_not_allowed",
            message=f"Method {request.method!r} is not allowed for /api/v1/{issue_identifier}.",
            status=405,
        )
        response["Allow"] = ALLOWED_ISSUE_METHODS
        return response

    try:
        issue_snapshot = get_runtime_issue_snapshot(issue_identifier)
    except RuntimeIssueNotFoundError as exc:
        return _error_response(code="issue_not_found", message=str(exc), status=404)
    except RuntimeSnapshotUnavailableError as exc:
        return _error_response(code="unavailable", message=str(exc), status=503)
    except TimeoutError as exc:
        return _error_response(code="timeout", message=str(exc), status=503)

    return JsonResponse(issue_snapshot)


@csrf_exempt
def runtime_refresh(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        response = _error_response(
            code="method_not_allowed",
            message=f"Method {request.method!r} is not allowed for /api/v1/refresh.",
            status=405,
        )
        response["Allow"] = ALLOWED_REFRESH_METHODS
        return response

    try:
        refresh_request = queue_runtime_refresh_request()
    except RuntimeSnapshotUnavailableError as exc:
        return _error_response(code="unavailable", message=str(exc), status=503)
    except TimeoutError as exc:
        return _error_response(code="timeout", message=str(exc), status=503)

    return JsonResponse(refresh_request, status=202)


@csrf_exempt
def tracker_comment(request: HttpRequest, issue_identifier: str) -> JsonResponse:
    if request.method != "POST":
        response = _error_response(
            code="method_not_allowed",
            message=(
                f"Method {request.method!r} is not allowed for "
                f"/api/v1/tracker/issues/{issue_identifier}/comments."
            ),
            status=405,
        )
        response["Allow"] = ALLOWED_TRACKER_MUTATION_METHODS
        return response

    try:
        payload = _parse_json_body(request)
        service = _build_tracker_mutation_service()
        result = service.add_comment(
            TrackerCommentRequest(
                issue_identifier=issue_identifier,
                body=_require_string_field(payload, "body"),
            )
        )
    except (WorkflowError, WorkflowConfigError) as exc:
        return _error_response(code=exc.code, message=exc.message, status=503)
    except TrackerIssueNotFoundError as exc:
        return _error_response(code=exc.code, message=exc.message, status=404)
    except TrackerValidationError as exc:
        return _error_response(code=exc.code, message=exc.message, status=400)
    except TrackerMutationError as exc:
        return _error_response(code=exc.code, message=exc.message, status=502)

    return JsonResponse(
        {
            "operation": "comment",
            "status": result.status,
            "issue": {"id": result.issue_id, "identifier": result.issue_identifier},
            "comment": {
                "id": result.comment_id,
                "body": result.body,
                "url": result.url,
            },
        }
    )


@csrf_exempt
def tracker_transition(request: HttpRequest, issue_identifier: str) -> JsonResponse:
    if request.method != "POST":
        response = _error_response(
            code="method_not_allowed",
            message=(
                f"Method {request.method!r} is not allowed for "
                f"/api/v1/tracker/issues/{issue_identifier}/transition."
            ),
            status=405,
        )
        response["Allow"] = ALLOWED_TRACKER_MUTATION_METHODS
        return response

    try:
        payload = _parse_json_body(request)
        service = _build_tracker_mutation_service()
        result = service.transition_issue(
            TrackerTransitionRequest(
                issue_identifier=issue_identifier,
                target_state=_require_string_field(payload, "target_state"),
            )
        )
    except (WorkflowError, WorkflowConfigError) as exc:
        return _error_response(code=exc.code, message=exc.message, status=503)
    except TrackerIssueNotFoundError as exc:
        return _error_response(code=exc.code, message=exc.message, status=404)
    except TrackerValidationError as exc:
        return _error_response(code=exc.code, message=exc.message, status=400)
    except TrackerMutationError as exc:
        status = 409 if exc.code == "invalid_state_transition" else 502
        return _error_response(code=exc.code, message=exc.message, status=status)

    return JsonResponse(
        {
            "operation": "state_transition",
            "status": result.status,
            "issue": {"id": result.issue_id, "identifier": result.issue_identifier},
            "transition": {
                "from_state": result.from_state,
                "to_state": result.to_state,
            },
        }
    )


@csrf_exempt
def tracker_pull_request(request: HttpRequest, issue_identifier: str) -> JsonResponse:
    if request.method != "POST":
        response = _error_response(
            code="method_not_allowed",
            message=(
                f"Method {request.method!r} is not allowed for "
                f"/api/v1/tracker/issues/{issue_identifier}/pull-request."
            ),
            status=405,
        )
        response["Allow"] = ALLOWED_TRACKER_MUTATION_METHODS
        return response

    try:
        payload = _parse_json_body(request)
        service = _build_tracker_mutation_service()
        result = service.attach_pull_request(
            TrackerPullRequestRequest(
                issue_identifier=issue_identifier,
                url=_require_string_field(payload, "url"),
                title=_require_string_field(payload, "title"),
                subtitle=_optional_string_field(payload, "subtitle"),
                branch_name=_optional_string_field(payload, "branch_name"),
                repository=_optional_string_field(payload, "repository"),
                status=_optional_string_field(payload, "status"),
                metadata=_optional_metadata_field(payload, "metadata"),
            )
        )
    except (WorkflowError, WorkflowConfigError) as exc:
        return _error_response(code=exc.code, message=exc.message, status=503)
    except TrackerIssueNotFoundError as exc:
        return _error_response(code=exc.code, message=exc.message, status=404)
    except TrackerValidationError as exc:
        return _error_response(code=exc.code, message=exc.message, status=400)
    except TrackerMutationError as exc:
        return _error_response(code=exc.code, message=exc.message, status=502)

    return JsonResponse(
        {
            "operation": "pull_request_attachment",
            "status": result.status,
            "issue": {"id": result.issue_id, "identifier": result.issue_identifier},
            "pull_request": {
                "attachment_id": result.issue_link.id,
                "title": result.issue_link.title,
                "url": result.issue_link.url,
                "subtitle": result.issue_link.subtitle,
                "metadata": result.issue_link.metadata,
            },
        }
    )


def _error_response(*, code: str, message: str, status: int) -> JsonResponse:
    return JsonResponse(
        {"error": {"code": code, "message": message}},
        status=status,
    )


def _html_response(*, title: str, body: str, status: int = 200) -> HttpResponse:
    return HttpResponse(
        (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f"<title>{escape(title)}</title>"
            "<style>"
            "body{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;"
            "margin:2rem;line-height:1.4}"
            "table{border-collapse:collapse;width:100%;margin-bottom:1.5rem}"
            "th,td{border:1px solid #d0d7de;padding:.5rem;text-align:left;vertical-align:top}"
            "code{background:#f6f8fa;padding:.1rem .3rem;border-radius:.25rem}"
            "a{color:#0b5fff}"
            "</style></head><body>"
            f"<h1>{escape(title)}</h1>{body}</body></html>"
        ),
        status=status,
        content_type="text/html; charset=utf-8",
    )


def _render_running_row(entry: object) -> str:
    if not isinstance(entry, dict):
        return ""
    return (
        "<tr>"
        f"<td>{_render_issue_link(entry)}</td>"
        f"<td>{escape(str(entry.get('state', '')))}</td>"
        f"<td>{escape(str(entry.get('session_id', '')))}</td>"
        f"<td>{escape(str(entry.get('last_event', '')))}</td>"
        f"<td><code>{escape(str(entry.get('workspace_path', '')))}</code></td>"
        "</tr>"
    )


def _render_retry_row(entry: object) -> str:
    if not isinstance(entry, dict):
        return ""
    return (
        "<tr>"
        f"<td>{_render_issue_link(entry)}</td>"
        f"<td>{escape(str(entry.get('attempt', '')))}</td>"
        f"<td>{escape(str(entry.get('due_at', '')))}</td>"
        f"<td>{escape(str(entry.get('error', '')))}</td>"
        f"<td><code>{escape(str(entry.get('workspace_path', '')))}</code></td>"
        "</tr>"
    )


def _render_issue_link(entry: dict[str, object]) -> str:
    raw_issue_identifier = str(entry.get("issue_identifier", ""))
    issue_identifier = escape(raw_issue_identifier)
    return f'<a href="/api/v1/{quote(raw_issue_identifier, safe="")}">{issue_identifier}</a>'


@functools.cache
def _build_tracker_mutation_service() -> TrackerMutationService:
    definition = load_workflow_definition()
    config = build_service_config(definition)
    validate_dispatch_config(config)
    return build_tracker_mutation_service(config)


def _parse_json_body(request: HttpRequest) -> dict[str, object]:
    try:
        raw_body = request.body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TrackerValidationError("Request body must be valid UTF-8 JSON.") from exc

    try:
        payload = json.loads(raw_body or "{}")
    except json.JSONDecodeError as exc:
        raise TrackerValidationError("Request body must be valid JSON.") from exc

    if not isinstance(payload, dict):
        raise TrackerValidationError("Request body must decode to a JSON object.")
    return payload


def _require_string_field(payload: dict[str, object], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str):
        raise TrackerValidationError(f"Field '{field_name}' must be a string.")
    return value


def _optional_string_field(payload: dict[str, object], field_name: str) -> str | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TrackerValidationError(f"Field '{field_name}' must be a string when provided.")
    return value


def _optional_metadata_field(
    payload: dict[str, object], field_name: str
) -> dict[str, str | int | float | bool]:
    value = payload.get(field_name)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TrackerValidationError(f"Field '{field_name}' must be an object when provided.")

    metadata: dict[str, str | int | float | bool] = {}
    for raw_key, raw_value in value.items():
        if not isinstance(raw_key, str):
            raise TrackerValidationError(f"Field '{field_name}' must use string keys.")
        if not isinstance(raw_value, str | int | float | bool):
            raise TrackerValidationError(
                f"Field '{field_name}' values must be strings, numbers, or booleans."
            )
        metadata[raw_key] = raw_value
    return metadata
