from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.request import Request, urlopen

from symphony.workflow.config import PlaneTrackerConfig

from .plane import PlanePayloadError

DEFAULT_PLANE_TIMEOUT_MS = 30_000
DEFAULT_PLANE_PAGE_SIZE = 50
PLANE_ISSUES_PATH_TEMPLATE = "/api/v1/workspaces/{workspace_slug}/projects/{project_id}/issues/"


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
    next_offset: int | None
    count: int | None


@dataclass(slots=True)
class PlaneTrackerClient:
    tracker_config: PlaneTrackerConfig
    timeout_ms: int = DEFAULT_PLANE_TIMEOUT_MS
    transport: PlaneTransport | None = None

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
        return _decode_payload(response)

    def _send_request(
        self,
        *,
        transport: PlaneTransport,
        path: str,
        query_params: Mapping[str, object],
    ) -> PlaneTransportResponse:
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

        if response.status_code < 200 or response.status_code >= 300:
            raise PlaneAPIStatusError(f"Plane API responded with HTTP {response.status_code}.")

        return response


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

    return PlaneIssuePage(
        items=tuple(normalized_results),
        next_offset=_extract_next_offset(payload.get("next")),
        count=count,
    )


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
