from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.request import Request, urlopen

from symphony.workflow.config import PlaneTrackerConfig

from .models import Issue
from .plane import PlanePayloadError, normalize_plane_issue
from .write_contract import TrackerIssueReference

DEFAULT_PLANE_TIMEOUT_MS = 30_000
DEFAULT_PLANE_PAGE_SIZE = 50
PLANE_ISSUES_PATH_TEMPLATE = "/api/v1/workspaces/{workspace_slug}/projects/{project_id}/issues/"
PLANE_ISSUE_PATH_TEMPLATE = f"{PLANE_ISSUES_PATH_TEMPLATE}{{issue_id}}/"
PLANE_ISSUE_EXPAND = "state,project,labels,blocked_by_issues"


class PlaneAPIError(Exception):
    code = "plane_api_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class PlaneAPIRequestError(PlaneAPIError):
    code = "plane_api_request"


class PlaneAPIStatusError(PlaneAPIError):
    code = "plane_api_status"


@dataclass(slots=True, frozen=True)
class PlaneTransportResponse:
    status_code: int
    body: str


class PlaneTransport(Protocol):
    def __call__(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        query_params: Mapping[str, object],
        timeout_ms: int,
    ) -> PlaneTransportResponse: ...


@dataclass(slots=True, frozen=True)
class PlaneIssuePage:
    items: tuple[Mapping[str, Any], ...]
    next_cursor: str | None
    next_offset: int | None
    count: int | None


@dataclass(slots=True)
class PlaneTrackerClient:
    tracker_config: PlaneTrackerConfig
    timeout_ms: int = DEFAULT_PLANE_TIMEOUT_MS
    transport: PlaneTransport | None = None

    def fetch_candidate_issues(self) -> list[Issue]:
        return self.fetch_issues_by_states(self.tracker_config.active_states)

    def fetch_issues_by_states(self, state_names: Sequence[str]) -> list[Issue]:
        requested_state_names = _normalize_state_names(state_names)
        if not requested_state_names:
            return []

        requested_state_names_lower = {state_name.lower() for state_name in requested_state_names}
        issues: list[Issue] = []
        cursor: str | None = None

        while True:
            page = self._fetch_cursor_issue_page(cursor=cursor)
            for item in page.items:
                issue = normalize_plane_issue(item)
                if issue.state.lower() in requested_state_names_lower:
                    issues.append(issue)

            if page.next_cursor is None:
                return issues
            cursor = page.next_cursor

    def fetch_issue_states_by_ids(self, issue_ids: Sequence[str]) -> list[Issue]:
        requested_issue_ids = _normalize_issue_ids(issue_ids)
        if not requested_issue_ids:
            return []

        issues: list[Issue] = []
        for issue_id in requested_issue_ids:
            issue_payload = self._fetch_optional_issue_json(
                issue_id=issue_id,
                query_params={"expand": PLANE_ISSUE_EXPAND},
            )
            if issue_payload is None:
                continue
            issues.append(normalize_plane_issue(issue_payload))
        return issues

    def get_issue_reference(self, issue_identifier: str) -> TrackerIssueReference | None:
        normalized_issue_identifier = issue_identifier.strip()
        if not normalized_issue_identifier:
            return None

        issue_payload = self._find_issue_payload(normalized_issue_identifier)
        if issue_payload is None:
            return None

        return _normalize_issue_reference(
            issue_payload,
            default_project_ref=self.tracker_config.project_id,
        )

    def fetch_issue_page(
        self,
        *,
        limit: int = DEFAULT_PLANE_PAGE_SIZE,
        offset: int = 0,
        query_params: Mapping[str, object] | None = None,
    ) -> PlaneIssuePage:
        payload = self._fetch_json(
            path=PLANE_ISSUES_PATH_TEMPLATE.format(
                workspace_slug=quote(self.tracker_config.workspace_slug or "", safe=""),
                project_id=quote(self.tracker_config.project_id or "", safe=""),
            ),
            query_params={
                "limit": limit,
                "offset": offset,
                **(dict(query_params) if query_params is not None else {}),
            },
        )
        return _extract_issue_page(payload)

    def build_issue_collection_url(self) -> str:
        return build_plane_issue_collection_url(self.tracker_config)

    def _fetch_json(
        self,
        *,
        path: str,
        query_params: Mapping[str, object],
    ) -> Mapping[str, Any]:
        transport = self.transport or _default_plane_transport
        response = self._send_request(
            transport=transport,
            path=path,
            query_params=query_params,
        )
        if response is None:
            raise PlaneAPIRequestError("Plane API request failed.")
        return _decode_payload(response)

    def _fetch_optional_issue_json(
        self,
        *,
        issue_id: str,
        query_params: Mapping[str, object],
    ) -> Mapping[str, Any] | None:
        transport = self.transport or _default_plane_transport
        response = self._send_request(
            transport=transport,
            path=PLANE_ISSUE_PATH_TEMPLATE.format(
                workspace_slug=quote(self.tracker_config.workspace_slug or "", safe=""),
                project_id=quote(self.tracker_config.project_id or "", safe=""),
                issue_id=quote(issue_id, safe=""),
            ),
            query_params=query_params,
            allow_not_found=True,
        )
        if response is None:
            return None
        return _decode_payload(response)

    def _send_request(
        self,
        *,
        transport: PlaneTransport,
        path: str,
        query_params: Mapping[str, object],
        allow_not_found: bool = False,
    ) -> PlaneTransportResponse | None:
        try:
            response = transport(
                url=_join_base_url(self.tracker_config.api_base_url or "", path),
                headers={
                    "Accept": "application/json",
                    "X-API-Key": self.tracker_config.api_key or "",
                },
                query_params=query_params,
                timeout_ms=self.timeout_ms,
            )
        except PlaneAPIError:
            raise
        except Exception as exc:
            raise PlaneAPIRequestError("Plane API request failed.") from exc

        if allow_not_found and response.status_code == 404:
            return None
        if response.status_code < 200 or response.status_code >= 300:
            raise PlaneAPIStatusError(f"Plane API responded with HTTP {response.status_code}.")

        return response

    def _fetch_cursor_issue_page(self, *, cursor: str | None) -> PlaneIssuePage:
        query_params: dict[str, object] = {
            "per_page": DEFAULT_PLANE_PAGE_SIZE,
            "expand": PLANE_ISSUE_EXPAND,
        }
        if cursor is not None:
            query_params["cursor"] = cursor

        payload = self._fetch_json(
            path=PLANE_ISSUES_PATH_TEMPLATE.format(
                workspace_slug=quote(self.tracker_config.workspace_slug or "", safe=""),
                project_id=quote(self.tracker_config.project_id or "", safe=""),
            ),
            query_params=query_params,
        )
        return _extract_issue_page(payload)

    def _find_issue_payload(self, issue_identifier: str) -> Mapping[str, Any] | None:
        # Plane has no server-side filter by identifier, so we scan all pages until we find a match.
        cursor: str | None = None
        while True:
            page = self._fetch_cursor_issue_page(cursor=cursor)
            for item in page.items:
                normalized_issue = normalize_plane_issue(item)
                if normalized_issue.identifier == issue_identifier:
                    return item

            if page.next_cursor is None:
                return None
            cursor = page.next_cursor


def build_plane_issue_collection_url(tracker_config: PlaneTrackerConfig) -> str:
    return _join_base_url(
        tracker_config.api_base_url or "",
        PLANE_ISSUES_PATH_TEMPLATE.format(
            workspace_slug=quote(tracker_config.workspace_slug or "", safe=""),
            project_id=quote(tracker_config.project_id or "", safe=""),
        ),
    )


def _default_plane_transport(
    *,
    url: str,
    headers: Mapping[str, str],
    query_params: Mapping[str, object],
    timeout_ms: int,
) -> PlaneTransportResponse:
    request_url = _append_query_params(url, query_params)
    request = Request(request_url, headers=dict(headers), method="GET")

    try:
        with urlopen(request, timeout=timeout_ms / 1000) as response:
            body = response.read().decode("utf-8")
            return PlaneTransportResponse(status_code=response.status, body=body)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return PlaneTransportResponse(status_code=exc.code, body=body)
    except (URLError, OSError) as exc:
        raise PlaneAPIRequestError("Plane API request failed.") from exc


def _join_base_url(base_url: str, path: str) -> str:
    normalized_base_url = (base_url or "").rstrip("/")
    return f"{normalized_base_url}{path}"


def _append_query_params(url: str, query_params: Mapping[str, object]) -> str:
    encoded_query = urlencode(_normalize_query_params(query_params), doseq=True)
    if not encoded_query:
        return url
    return f"{url}?{encoded_query}"


def _normalize_query_params(query_params: Mapping[str, object]) -> list[tuple[str, str]]:
    normalized: list[tuple[str, str]] = []
    for key, value in query_params.items():
        if value is None:
            continue
        if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
            for item in value:
                normalized_item = _normalize_query_param_value(key, item)
                if normalized_item is not None:
                    normalized.append((key, normalized_item))
            continue

        normalized_value = _normalize_query_param_value(key, value)
        if normalized_value is not None:
            normalized.append((key, normalized_value))

    return normalized


def _normalize_query_param_value(key: str, value: object) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        normalized = value.strip()
        if normalized:
            return normalized
        return None

    raise PlaneAPIRequestError(f"Plane request contains malformed query parameter: {key}.")


def _decode_payload(response: PlaneTransportResponse) -> Mapping[str, Any]:
    try:
        payload = json.loads(response.body)
    except json.JSONDecodeError as exc:
        raise PlanePayloadError("Plane response body must be valid JSON.") from exc

    if not isinstance(payload, Mapping):
        raise PlanePayloadError("Plane response body must be a JSON object.")

    return payload


def _extract_issue_page(payload: Mapping[str, Any]) -> PlaneIssuePage:
    results = payload.get("results")
    if not isinstance(results, list):
        raise PlanePayloadError("Plane issue response is missing results.")

    normalized_results: list[Mapping[str, Any]] = []
    for result in results:
        if not isinstance(result, Mapping):
            raise PlanePayloadError("Plane issue response contains a malformed result.")
        normalized_results.append(result)

    count = payload.get("count")
    if count is not None and (isinstance(count, bool) or not isinstance(count, int) or count < 0):
        raise PlanePayloadError("Plane issue response contains a malformed count.")

    next_cursor = _extract_next_cursor(payload)
    return PlaneIssuePage(
        items=tuple(normalized_results),
        next_cursor=next_cursor,
        next_offset=_extract_next_offset(payload.get("next")),
        count=count,
    )


def _extract_next_cursor(payload: Mapping[str, Any]) -> str | None:
    value = payload.get("next_cursor")
    if value is None:
        return None
    if not isinstance(value, str):
        raise PlanePayloadError("Plane issue response contains a malformed next_cursor.")
    normalized = value.strip()
    return normalized or None


def _extract_next_offset(value: Any) -> int | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise PlanePayloadError("Plane issue response contains a malformed next page URL.")

    parsed = urlparse(value)
    query = parse_qs(parsed.query)
    offsets = query.get("offset")
    if not offsets or not offsets[0]:
        raise PlanePayloadError("Plane issue response next page URL is missing offset.")

    try:
        next_offset = int(offsets[0])
    except ValueError as exc:
        raise PlanePayloadError(
            "Plane issue response next page URL contains an invalid offset."
        ) from exc

    if next_offset < 0:
        raise PlanePayloadError("Plane issue response next page URL contains an invalid offset.")

    return next_offset


def _normalize_state_names(state_names: Sequence[str]) -> list[str]:
    normalized_state_names: list[str] = []
    for state_name in state_names:
        normalized = state_name.strip()
        if normalized:
            normalized_state_names.append(normalized)
    return normalized_state_names


def _normalize_issue_ids(issue_ids: Sequence[str]) -> list[str]:
    normalized_issue_ids: list[str] = []
    for issue_id in issue_ids:
        normalized = issue_id.strip()
        if normalized:
            normalized_issue_ids.append(normalized)
    return normalized_issue_ids


def _normalize_issue_reference(
    payload: Mapping[str, Any],
    *,
    default_project_ref: str | None,
) -> TrackerIssueReference:
    issue = normalize_plane_issue(payload)
    state_id = _extract_issue_state_id(payload)
    project_ref = _extract_issue_project_ref(payload, default_project_ref=default_project_ref)
    return TrackerIssueReference(
        id=issue.id,
        identifier=issue.identifier,
        state_id=state_id,
        state_name=issue.state,
        workflow_scope_id=project_ref,
        project_ref=project_ref,
    )


def _extract_issue_state_id(payload: Mapping[str, Any]) -> str:
    state = payload.get("state") or payload.get("state_detail") or payload.get("stateDetail")
    if isinstance(state, Mapping):
        state_id = state.get("id")
    else:
        state_id = state

    if not isinstance(state_id, str) or not state_id.strip():
        raise PlanePayloadError("Plane issue payload is missing state.id.")
    return state_id.strip()


def _extract_issue_project_ref(
    payload: Mapping[str, Any],
    *,
    default_project_ref: str | None,
) -> str:
    project = (
        payload.get("project")
        or payload.get("project_detail")
        or payload.get("projectDetail")
        or payload.get("project_id")
        or payload.get("projectId")
    )
    if isinstance(project, Mapping):
        candidate = project.get("id")
    else:
        candidate = project

    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    if default_project_ref is not None and default_project_ref.strip():
        return default_project_ref.strip()
    raise PlanePayloadError("Plane issue payload is missing project.id.")
