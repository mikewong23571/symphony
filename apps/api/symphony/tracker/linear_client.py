from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from symphony.workflow.config import TrackerConfig

from .linear import LinearPayloadError, normalize_linear_issue
from .models import Issue

DEFAULT_LINEAR_TIMEOUT_MS = 30_000
DEFAULT_LINEAR_PAGE_SIZE = 50

FETCH_ISSUES_BY_STATES_QUERY = """
query FetchIssuesByStates($projectSlug: String!, $stateNames: [String!]!) {
  issues(
    filter: {
      project: { slugId: { eq: $projectSlug } }
      state: { name: { in: $stateNames } }
    }
  ) {
    nodes {
      id
      identifier
      title
      description
      priority
      state {
        name
      }
      branchName
      url
      labels {
        nodes {
          name
        }
      }
      inverseRelations {
        nodes {
          type
          issue {
            id
            identifier
            state {
              name
            }
          }
          relatedIssue {
            id
            identifier
            state {
              name
            }
          }
        }
      }
      createdAt
      updatedAt
    }
  }
}
""".strip()

FETCH_CANDIDATE_ISSUES_QUERY = """
query FetchCandidateIssues(
  $projectSlug: String!
  $stateNames: [String!]!
  $first: Int!
  $after: String
) {
  issues(
    first: $first
    after: $after
    filter: {
      project: { slugId: { eq: $projectSlug } }
      state: { name: { in: $stateNames } }
    }
  ) {
    nodes {
      id
      identifier
      title
      description
      priority
      state {
        name
      }
      branchName
      url
      labels {
        nodes {
          name
        }
      }
      inverseRelations {
        nodes {
          type
          issue {
            id
            identifier
            state {
              name
            }
          }
          relatedIssue {
            id
            identifier
            state {
              name
            }
          }
        }
      }
      createdAt
      updatedAt
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
""".strip()

FETCH_ISSUE_STATES_BY_IDS_QUERY = """
query FetchIssueStatesByIds($issueIds: [ID!]!) {
  issues(filter: { id: { in: $issueIds } }) {
    nodes {
      id
      identifier
      title
      state {
        name
      }
    }
  }
}
""".strip()


class LinearAPIError(Exception):
    code = "linear_api_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class LinearAPIRequestError(LinearAPIError):
    code = "linear_api_request"


class LinearAPIStatusError(LinearAPIError):
    code = "linear_api_status"


class LinearGraphQLError(LinearAPIError):
    code = "linear_graphql_errors"


class LinearMissingEndCursorError(LinearAPIError):
    code = "linear_missing_end_cursor"


@dataclass(slots=True, frozen=True)
class LinearTransportResponse:
    status_code: int
    body: str


class LinearTransport(Protocol):
    def __call__(
        self,
        *,
        endpoint: str,
        headers: Mapping[str, str],
        query: str,
        variables: Mapping[str, object],
        timeout_ms: int,
    ) -> LinearTransportResponse: ...


@dataclass(slots=True)
class LinearTrackerClient:
    tracker_config: TrackerConfig
    timeout_ms: int = DEFAULT_LINEAR_TIMEOUT_MS
    transport: LinearTransport | None = None

    def fetch_candidate_issues(self) -> list[Issue]:
        requested_state_names = _normalize_state_names(self.tracker_config.active_states)
        if not requested_state_names:
            return []

        after: str | None = None
        issues: list[Issue] = []

        while True:
            payload = self._fetch_graphql_payload(
                query=FETCH_CANDIDATE_ISSUES_QUERY,
                variables={
                    "projectSlug": self.tracker_config.project_slug or "",
                    "stateNames": requested_state_names,
                    "first": DEFAULT_LINEAR_PAGE_SIZE,
                    "after": after,
                },
            )
            issues_connection = _extract_issues_connection(payload)
            issue_nodes = _extract_issue_nodes(issues_connection)
            issues.extend(normalize_linear_issue(issue_node) for issue_node in issue_nodes)

            page_info = _extract_page_info(issues_connection)
            if not page_info.has_next_page:
                return issues
            if page_info.end_cursor is None:
                raise LinearMissingEndCursorError(
                    "Linear candidate issue response is missing pageInfo.endCursor."
                )
            after = page_info.end_cursor

    def fetch_issues_by_states(self, state_names: Sequence[str]) -> list[Issue]:
        requested_state_names = _normalize_state_names(state_names)
        if not requested_state_names:
            return []

        payload = self._fetch_graphql_payload(
            query=FETCH_ISSUES_BY_STATES_QUERY,
            variables={
                "projectSlug": self.tracker_config.project_slug or "",
                "stateNames": requested_state_names,
            },
        )
        issue_nodes = _extract_issue_nodes(_extract_issues_connection(payload))
        return [normalize_linear_issue(issue_node) for issue_node in issue_nodes]

    def fetch_issue_states_by_ids(self, issue_ids: Sequence[str]) -> list[Issue]:
        requested_issue_ids = _normalize_issue_ids(issue_ids)
        if not requested_issue_ids:
            return []

        payload = self._fetch_graphql_payload(
            query=FETCH_ISSUE_STATES_BY_IDS_QUERY,
            variables={"issueIds": requested_issue_ids},
        )
        issue_nodes = _extract_issue_nodes(_extract_issues_connection(payload))
        return [normalize_linear_issue(issue_node) for issue_node in issue_nodes]

    def _fetch_graphql_payload(
        self,
        *,
        query: str,
        variables: Mapping[str, object],
    ) -> Mapping[str, Any]:
        transport = self.transport or _default_linear_transport
        response = self._send_graphql_request(
            transport=transport,
            query=query,
            variables=variables,
        )
        return _decode_graphql_payload(response)

    def _send_graphql_request(
        self,
        *,
        transport: LinearTransport,
        query: str,
        variables: Mapping[str, object],
    ) -> LinearTransportResponse:
        try:
            response = transport(
                endpoint=self.tracker_config.endpoint,
                headers={
                    "Authorization": self.tracker_config.api_key or "",
                    "Content-Type": "application/json",
                },
                query=query,
                variables=variables,
                timeout_ms=self.timeout_ms,
            )
        except LinearAPIError:
            raise
        except Exception as exc:
            raise LinearAPIRequestError("Linear API request failed.") from exc

        if response.status_code != 200:
            raise LinearAPIStatusError(f"Linear API responded with HTTP {response.status_code}.")

        return response


def _default_linear_transport(
    *,
    endpoint: str,
    headers: Mapping[str, str],
    query: str,
    variables: Mapping[str, object],
    timeout_ms: int,
) -> LinearTransportResponse:
    payload = json.dumps({"query": query, "variables": dict(variables)}).encode("utf-8")
    request = Request(endpoint, data=payload, headers=dict(headers), method="POST")

    try:
        with urlopen(request, timeout=timeout_ms / 1000) as response:
            body = response.read().decode("utf-8")
            return LinearTransportResponse(status_code=response.status, body=body)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return LinearTransportResponse(status_code=exc.code, body=body)
    except (URLError, OSError) as exc:
        raise LinearAPIRequestError("Linear API request failed.") from exc


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


def _decode_graphql_payload(response: LinearTransportResponse) -> Mapping[str, Any]:
    try:
        payload = json.loads(response.body)
    except json.JSONDecodeError as exc:
        raise LinearPayloadError("Linear GraphQL response body must be valid JSON.") from exc

    if not isinstance(payload, Mapping):
        raise LinearPayloadError("Linear GraphQL response body must be a JSON object.")

    graphql_errors = payload.get("errors")
    if graphql_errors:
        raise LinearGraphQLError("Linear GraphQL response returned top-level errors.")

    return payload


@dataclass(slots=True, frozen=True)
class LinearPageInfo:
    has_next_page: bool
    end_cursor: str | None


def _extract_issues_connection(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise LinearPayloadError("Linear GraphQL response is missing data.")

    issues = data.get("issues")
    if not isinstance(issues, Mapping):
        raise LinearPayloadError("Linear GraphQL response is missing data.issues.")

    return issues


def _extract_issue_nodes(issues: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    nodes = issues.get("nodes")
    if not isinstance(nodes, list):
        raise LinearPayloadError("Linear GraphQL response is missing data.issues.nodes.")

    normalized_nodes: list[Mapping[str, Any]] = []
    for node in nodes:
        if not isinstance(node, Mapping):
            raise LinearPayloadError("Linear GraphQL response contains a malformed issue node.")
        normalized_nodes.append(node)

    return normalized_nodes


def _extract_page_info(issues: Mapping[str, Any]) -> LinearPageInfo:
    page_info = issues.get("pageInfo")
    if not isinstance(page_info, Mapping):
        raise LinearPayloadError("Linear GraphQL response is missing data.issues.pageInfo.")

    has_next_page = page_info.get("hasNextPage")
    if not isinstance(has_next_page, bool):
        raise LinearPayloadError(
            "Linear GraphQL response is missing data.issues.pageInfo.hasNextPage."
        )

    end_cursor = page_info.get("endCursor")
    if end_cursor is not None and not isinstance(end_cursor, str):
        raise LinearPayloadError(
            "Linear GraphQL response is missing data.issues.pageInfo.endCursor."
        )

    return LinearPageInfo(has_next_page=has_next_page, end_cursor=end_cursor)
