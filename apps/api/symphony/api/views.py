from __future__ import annotations

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

ALLOWED_DASHBOARD_METHODS = "GET, HEAD"
ALLOWED_STATE_METHODS = "GET, HEAD"
ALLOWED_ISSUE_METHODS = "GET, HEAD"
ALLOWED_REFRESH_METHODS = "POST"


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
