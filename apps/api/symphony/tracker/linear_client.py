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
from .write_contract import (
    JsonScalar,
    TrackerComment,
    TrackerIssueLink,
    TrackerIssueReference,
    TrackerWorkflowState,
    is_valid_json_scalar,
)

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

FETCH_TRACKER_ISSUE_REFERENCE_QUERY = """
query FetchTrackerIssueReference($projectSlug: String!, $issueIdentifier: String!) {
  issues(
    first: 1
    filter: {
      project: { slugId: { eq: $projectSlug } }
      identifier: { eq: $issueIdentifier }
    }
  ) {
    nodes {
      id
      identifier
      state {
        id
        name
      }
      team {
        id
      }
      project {
        slugId
      }
    }
  }
}
""".strip()

FETCH_WORKFLOW_STATES_QUERY = """
query FetchWorkflowStates($first: Int!, $after: String) {
  workflowStates(first: $first, after: $after) {
    nodes {
      id
      name
      team {
        id
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
""".strip()

CREATE_COMMENT_MUTATION = """
mutation CreateComment($issueId: String!, $body: String!) {
  commentCreate(input: { issueId: $issueId, body: $body }) {
    success
    comment {
      id
      body
      url
    }
  }
}
""".strip()

CREATE_ATTACHMENT_MUTATION = """
mutation CreateAttachment(
  $issueId: String!
  $title: String!
  $url: String!
  $subtitle: String
  $metadata: JSONObject
) {
  attachmentCreate(input: {
    issueId: $issueId
    title: $title
    url: $url
    subtitle: $subtitle
    metadata: $metadata
  }) {
    success
    attachment {
      id
      title
      url
      subtitle
      metadata
    }
  }
}
""".strip()

UPDATE_ISSUE_STATE_MUTATION = """
mutation UpdateIssueState($issueId: String!, $stateId: String!) {
  issueUpdate(id: $issueId, input: { stateId: $stateId }) {
    success
    issue {
      id
      identifier
      state {
        id
        name
      }
      team {
        id
      }
      project {
        slugId
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

    def get_issue_reference(self, issue_identifier: str) -> TrackerIssueReference | None:
        normalized_issue_identifier = issue_identifier.strip()
        if not normalized_issue_identifier:
            return None

        payload = self._fetch_graphql_payload(
            query=FETCH_TRACKER_ISSUE_REFERENCE_QUERY,
            variables={
                "projectSlug": self.tracker_config.project_slug or "",
                "issueIdentifier": normalized_issue_identifier,
            },
        )
        issue_node = _extract_optional_issue_reference_node(payload)
        if issue_node is None:
            return None
        return _normalize_issue_reference(issue_node)

    def list_workflow_states(self) -> list[TrackerWorkflowState]:
        after: str | None = None
        workflow_states: list[TrackerWorkflowState] = []

        while True:
            payload = self._fetch_graphql_payload(
                query=FETCH_WORKFLOW_STATES_QUERY,
                variables={
                    "first": DEFAULT_LINEAR_PAGE_SIZE,
                    "after": after,
                },
            )
            workflow_states_connection = _extract_workflow_states_connection(payload)
            workflow_states.extend(_extract_workflow_states(workflow_states_connection))

            page_info = _extract_page_info(
                workflow_states_connection,
                path="data.workflowStates",
            )
            if not page_info.has_next_page:
                return workflow_states
            if page_info.end_cursor is None:
                raise LinearMissingEndCursorError(
                    "Linear workflow state response is missing pageInfo.endCursor."
                )
            after = page_info.end_cursor

    def create_comment(self, issue_id: str, body: str) -> TrackerComment:
        payload = self._fetch_graphql_payload(
            query=CREATE_COMMENT_MUTATION,
            variables={"issueId": issue_id, "body": body},
        )
        mutation = _extract_mutation_payload(payload, "commentCreate")
        return _extract_comment(mutation)

    def update_issue_state(self, issue_id: str, state_id: str) -> TrackerIssueReference:
        payload = self._fetch_graphql_payload(
            query=UPDATE_ISSUE_STATE_MUTATION,
            variables={"issueId": issue_id, "stateId": state_id},
        )
        mutation = _extract_mutation_payload(payload, "issueUpdate")
        issue_node = mutation.get("issue")
        if not isinstance(issue_node, Mapping):
            raise LinearPayloadError("Linear issueUpdate response is missing issue data.")
        return _normalize_issue_reference(issue_node)

    def create_issue_link(
        self,
        *,
        issue_id: str,
        title: str,
        url: str,
        subtitle: str | None,
        metadata: Mapping[str, JsonScalar],
    ) -> TrackerIssueLink:
        validated_metadata = _validate_attachment_metadata(metadata)
        payload = self._fetch_graphql_payload(
            query=CREATE_ATTACHMENT_MUTATION,
            variables={
                "issueId": issue_id,
                "title": title,
                "url": url,
                "subtitle": subtitle,
                "metadata": validated_metadata or None,
            },
        )
        mutation = _extract_mutation_payload(payload, "attachmentCreate")
        return _extract_issue_link(mutation)

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


def _extract_data(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise LinearPayloadError("Linear GraphQL response is missing data.")
    return data


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


def _extract_optional_issue_reference_node(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    issues_connection = _extract_issues_connection(payload)
    issue_nodes = _extract_issue_nodes(issues_connection)
    if not issue_nodes:
        return None
    return issue_nodes[0]


def _extract_workflow_states_connection(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    data = _extract_data(payload)
    workflow_states = data.get("workflowStates")
    if not isinstance(workflow_states, Mapping):
        raise LinearPayloadError("Linear workflow state response is missing data.workflowStates.")
    return workflow_states


def _extract_workflow_states(workflow_states: Mapping[str, Any]) -> list[TrackerWorkflowState]:
    nodes = workflow_states.get("nodes")
    if not isinstance(nodes, list):
        raise LinearPayloadError(
            "Linear workflow state response is missing data.workflowStates.nodes."
        )

    normalized_states: list[TrackerWorkflowState] = []
    for node in nodes:
        if not isinstance(node, Mapping):
            raise LinearPayloadError("Linear workflow state response contains a malformed node.")
        normalized_states.append(_normalize_workflow_state(node))
    return normalized_states


def _extract_mutation_payload(payload: Mapping[str, Any], mutation_name: str) -> Mapping[str, Any]:
    data = _extract_data(payload)
    mutation = data.get(mutation_name)
    if not isinstance(mutation, Mapping):
        raise LinearPayloadError(f"Linear {mutation_name} response is missing mutation data.")

    success = mutation.get("success")
    if success is not True:
        raise LinearPayloadError(f"Linear {mutation_name} response did not report success.")
    return mutation


def _normalize_issue_reference(node: Mapping[str, Any]) -> TrackerIssueReference:
    issue_id = _require_string(node, "id", "Linear issue response is missing issue.id.")
    identifier = _require_string(
        node,
        "identifier",
        "Linear issue response is missing issue.identifier.",
    )
    state = node.get("state")
    if not isinstance(state, Mapping):
        raise LinearPayloadError("Linear issue response is missing issue.state.")
    state_id = _require_string(state, "id", "Linear issue response is missing issue.state.id.")
    state_name = _require_string(
        state,
        "name",
        "Linear issue response is missing issue.state.name.",
    )
    team = node.get("team")
    if not isinstance(team, Mapping):
        raise LinearPayloadError("Linear issue response is missing issue.team.")
    workflow_scope_id = _require_string(
        team,
        "id",
        "Linear issue response is missing issue.team.id.",
    )
    project = node.get("project")
    project_ref: str | None = None
    if project is not None:
        if not isinstance(project, Mapping):
            raise LinearPayloadError("Linear issue response contains a malformed issue.project.")
        raw_project_slug = project.get("slugId")
        if raw_project_slug is not None and not isinstance(raw_project_slug, str):
            raise LinearPayloadError(
                "Linear issue response contains a malformed issue.project.slugId."
            )
        project_ref = raw_project_slug
    return TrackerIssueReference(
        id=issue_id,
        identifier=identifier,
        state_id=state_id,
        state_name=state_name,
        workflow_scope_id=workflow_scope_id,
        project_ref=project_ref,
    )


def _normalize_workflow_state(node: Mapping[str, Any]) -> TrackerWorkflowState:
    state_id = _require_string(
        node,
        "id",
        "Linear workflow state response is missing workflow state id.",
    )
    name = _require_string(
        node,
        "name",
        "Linear workflow state response is missing workflow state name.",
    )
    team = node.get("team")
    if not isinstance(team, Mapping):
        raise LinearPayloadError("Linear workflow state response is missing workflow state team.")
    workflow_scope_id = _require_string(
        team,
        "id",
        "Linear workflow state response is missing workflow state team id.",
    )
    return TrackerWorkflowState(
        id=state_id,
        name=name,
        workflow_scope_id=workflow_scope_id,
    )


def _extract_comment(mutation: Mapping[str, Any]) -> TrackerComment:
    comment = mutation.get("comment")
    if not isinstance(comment, Mapping):
        raise LinearPayloadError("Linear commentCreate response is missing comment data.")
    comment_id = _require_string(
        comment,
        "id",
        "Linear commentCreate response is missing comment.id.",
    )
    body = _require_string(
        comment,
        "body",
        "Linear commentCreate response is missing comment.body.",
    )
    url = comment.get("url")
    if url is not None and not isinstance(url, str):
        raise LinearPayloadError("Linear commentCreate response contains a malformed comment.url.")
    return TrackerComment(id=comment_id, body=body, url=url)


def _extract_issue_link(mutation: Mapping[str, Any]) -> TrackerIssueLink:
    attachment = mutation.get("attachment")
    if not isinstance(attachment, Mapping):
        raise LinearPayloadError("Linear attachmentCreate response is missing attachment data.")
    attachment_id = _require_string(
        attachment,
        "id",
        "Linear attachmentCreate response is missing attachment.id.",
    )
    title = _require_string(
        attachment,
        "title",
        "Linear attachmentCreate response is missing attachment.title.",
    )
    url = _require_string(
        attachment,
        "url",
        "Linear attachmentCreate response is missing attachment.url.",
    )
    subtitle = attachment.get("subtitle")
    if subtitle is not None and not isinstance(subtitle, str):
        raise LinearPayloadError(
            "Linear attachmentCreate response contains a malformed attachment.subtitle."
        )
    metadata = attachment.get("metadata")
    if metadata is None:
        normalized_metadata: dict[str, JsonScalar] = {}
    else:
        normalized_metadata = _normalize_attachment_metadata(metadata)
    return TrackerIssueLink(
        id=attachment_id,
        title=title,
        url=url,
        subtitle=subtitle,
        metadata=normalized_metadata,
    )


def _normalize_attachment_metadata(value: object) -> dict[str, JsonScalar]:
    if not isinstance(value, Mapping):
        raise LinearPayloadError("Linear attachmentCreate response contains malformed metadata.")
    normalized: dict[str, JsonScalar] = {}
    for raw_key, raw_value in value.items():
        if not isinstance(raw_key, str):
            raise LinearPayloadError(
                "Linear attachmentCreate response contains malformed metadata."
            )
        if not is_valid_json_scalar(raw_value):
            raise LinearPayloadError(
                "Linear attachmentCreate response contains malformed metadata."
            )
        normalized[raw_key] = raw_value
    return normalized


def _require_string(payload: Mapping[str, Any], key: str, message: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise LinearPayloadError(message)
    return value


def _validate_attachment_metadata(metadata: Mapping[str, JsonScalar]) -> dict[str, JsonScalar]:
    normalized: dict[str, JsonScalar] = {}
    for key, value in metadata.items():
        if not is_valid_json_scalar(value):
            raise LinearPayloadError("Linear attachmentCreate request contains malformed metadata.")
        normalized[key] = value
    return normalized


def _extract_page_info(
    connection: Mapping[str, Any],
    *,
    path: str = "data.issues",
) -> LinearPageInfo:
    page_info = connection.get("pageInfo")
    if not isinstance(page_info, Mapping):
        raise LinearPayloadError(f"Linear GraphQL response is missing {path}.pageInfo.")

    has_next_page = page_info.get("hasNextPage")
    if not isinstance(has_next_page, bool):
        raise LinearPayloadError(f"Linear GraphQL response is missing {path}.pageInfo.hasNextPage.")

    end_cursor = page_info.get("endCursor")
    if end_cursor is not None and not isinstance(end_cursor, str):
        raise LinearPayloadError(f"Linear GraphQL response is missing {path}.pageInfo.endCursor.")

    return LinearPageInfo(has_next_page=has_next_page, end_cursor=end_cursor)
