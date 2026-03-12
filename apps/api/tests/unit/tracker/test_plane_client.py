from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest
from symphony.tracker import (
    PlaneAPIRequestError,
    PlaneAPIStatusError,
    PlanePayloadError,
    PlaneTrackerClient,
    PlaneTransportResponse,
    build_plane_issue_collection_url,
)
from symphony.tracker.plane_client import DEFAULT_PLANE_PAGE_SIZE
from symphony.workflow.config import PlaneTrackerConfig


class RecordingTransport:
    def __init__(
        self,
        *,
        response: PlaneTransportResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        query_params: Mapping[str, object],
        timeout_ms: int,
    ) -> PlaneTransportResponse:
        self.calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "query_params": dict(query_params),
                "timeout_ms": timeout_ms,
            }
        )

        if self.error is not None:
            raise self.error
        if self.response is None:
            raise AssertionError("Test transport expected a configured response.")
        return self.response


def make_tracker_config() -> PlaneTrackerConfig:
    return PlaneTrackerConfig(
        kind="plane",
        api_base_url="https://plane.example/self-hosted",
        api_key="plane-token",
        workspace_slug="engineering",
        project_id="project-123",
        active_states=("Todo", "In Progress"),
        terminal_states=("Done",),
    )


def test_build_plane_issue_collection_url_preserves_base_subpath_and_quotes_segments() -> None:
    config = PlaneTrackerConfig(
        kind="plane",
        api_base_url="https://plane.example/root",
        api_key="plane-token",
        workspace_slug="engineering team",
        project_id="project/123",
        active_states=("Todo",),
        terminal_states=("Done",),
    )

    url = build_plane_issue_collection_url(config)

    assert (
        url
        == "https://plane.example/root/api/v1/workspaces/engineering%20team/projects/project%2F123/issues/"
    )


def test_fetch_issue_page_sends_auth_headers_and_parses_next_offset() -> None:
    transport = RecordingTransport(
        response=PlaneTransportResponse(
            status_code=200,
            body=json.dumps(
                {
                    "count": 1,
                    "next": (
                        "https://plane.example/self-hosted/api/v1/workspaces/engineering/"
                        "projects/project-123/issues/?limit=50&offset=50"
                    ),
                    "results": [
                        {
                            "id": "issue-1",
                            "name": "Dispatch candidate",
                        }
                    ],
                }
            ),
        )
    )
    client = PlaneTrackerClient(make_tracker_config(), transport=transport)

    page = client.fetch_issue_page(
        query_params={
            "expand": ["state", "labels", "project"],
            "state": ["state-1", "state-2"],
        }
    )

    assert page.count == 1
    assert page.next_offset == 50
    assert page.items == ({"id": "issue-1", "name": "Dispatch candidate"},)
    assert len(transport.calls) == 1
    assert (
        transport.calls[0]["url"]
        == "https://plane.example/self-hosted/api/v1/workspaces/engineering/projects/project-123/issues/"
    )
    assert transport.calls[0]["headers"] == {
        "Accept": "application/json",
        "X-API-Key": "plane-token",
    }
    assert transport.calls[0]["query_params"] == {
        "limit": DEFAULT_PLANE_PAGE_SIZE,
        "offset": 0,
        "expand": ["state", "labels", "project"],
        "state": ["state-1", "state-2"],
    }
    assert transport.calls[0]["timeout_ms"] == 30_000


def test_fetch_issue_page_allows_final_page_without_next_link() -> None:
    client = PlaneTrackerClient(
        make_tracker_config(),
        transport=RecordingTransport(
            response=PlaneTransportResponse(
                status_code=200,
                body=json.dumps({"count": 1, "next": None, "results": [{"id": "issue-1"}]}),
            )
        ),
    )

    page = client.fetch_issue_page()

    assert page.next_offset is None


def test_fetch_issue_page_maps_transport_failures_to_typed_error() -> None:
    client = PlaneTrackerClient(
        make_tracker_config(),
        transport=RecordingTransport(error=OSError("network down")),
    )

    with pytest.raises(PlaneAPIRequestError, match="Plane API request failed."):
        client.fetch_issue_page()


def test_fetch_issue_page_maps_non_2xx_status_to_typed_error() -> None:
    client = PlaneTrackerClient(
        make_tracker_config(),
        transport=RecordingTransport(
            response=PlaneTransportResponse(status_code=503, body='{"error":"bad gateway"}')
        ),
    )

    with pytest.raises(PlaneAPIStatusError, match="HTTP 503"):
        client.fetch_issue_page()


@pytest.mark.parametrize(
    "body",
    [
        "not-json",
        json.dumps([]),
        json.dumps({"count": 1}),
        json.dumps({"results": ["bad-node"]}),
        json.dumps({"results": [], "count": "1"}),
        json.dumps({"results": [], "next": "https://plane.example/issues/?limit=50"}),
    ],
)
def test_fetch_issue_page_maps_malformed_payloads_to_typed_error(body: str) -> None:
    client = PlaneTrackerClient(
        make_tracker_config(),
        transport=RecordingTransport(
            response=PlaneTransportResponse(status_code=200, body=body),
        ),
    )

    with pytest.raises(PlanePayloadError):
        client.fetch_issue_page()
