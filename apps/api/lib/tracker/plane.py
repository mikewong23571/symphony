from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from html.parser import HTMLParser
from typing import Any

from .models import Issue, IssueBlocker


class PlanePayloadError(Exception):
    code = "plane_unknown_payload"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


_PLANE_PRIORITY_MAP = {
    "urgent": 1,
    "high": 2,
    "medium": 3,
    "normal": 3,
    "low": 4,
}


def normalize_plane_issue(
    payload: Mapping[str, Any],
    *,
    project_identifier: str | None = None,
) -> Issue:
    issue_id = _require_string(payload, "id")
    sequence_id = _require_sequence_id(payload)
    title = _extract_title(payload)
    state = _extract_state_name(payload)
    if state is None:
        raise PlanePayloadError("Plane issue payload is missing state.name.")

    resolved_project_identifier = project_identifier or _extract_project_identifier(payload)
    if resolved_project_identifier is None:
        raise PlanePayloadError("Plane issue payload is missing project.identifier.")

    return Issue(
        id=issue_id,
        identifier=f"{resolved_project_identifier}-{sequence_id}",
        title=title,
        description=_extract_description(payload),
        priority=_normalize_priority(payload.get("priority")),
        state=state,
        branch_name=_extract_branch_name(payload),
        url=_optional_string(payload.get("url")),
        labels=_normalize_labels(payload.get("labels")),
        blocked_by=_normalize_blocked_by(payload),
        created_at=_parse_timestamp(payload.get("created_at") or payload.get("createdAt")),
        updated_at=_parse_timestamp(payload.get("updated_at") or payload.get("updatedAt")),
    )


def _require_string(payload: Mapping[str, Any], key: str) -> str:
    value = _optional_string(payload.get(key))
    if value is None:
        raise PlanePayloadError(f"Plane issue payload is missing {key}.")
    return value


def _require_sequence_id(payload: Mapping[str, Any]) -> str:
    sequence_id = _optional_identifier(payload.get("sequence_id") or payload.get("sequenceId"))
    if sequence_id is None:
        raise PlanePayloadError("Plane issue payload is missing sequence_id.")
    return sequence_id


def _extract_title(payload: Mapping[str, Any]) -> str:
    title = _optional_string(payload.get("name") or payload.get("title"))
    if title is None:
        raise PlanePayloadError("Plane issue payload is missing name.")
    return title


def _extract_description(payload: Mapping[str, Any]) -> str | None:
    text_description = _optional_string(
        payload.get("description_stripped")
        or payload.get("descriptionStripped")
        or payload.get("description_text")
        or payload.get("description")
    )
    if text_description is not None:
        return text_description

    html_description = _optional_string(payload.get("description_html"))
    if html_description is None:
        return None
    return _strip_html_description(html_description)


def _extract_branch_name(payload: Mapping[str, Any]) -> str | None:
    return _optional_string(
        payload.get("branch_name")
        or payload.get("branchName")
        or payload.get("github_branch_name")
        or payload.get("githubBranchName")
    )


def _extract_state_name(payload: Mapping[str, Any]) -> str | None:
    state_value = payload.get("state") or payload.get("state_detail") or payload.get("stateDetail")
    if isinstance(state_value, Mapping):
        return _optional_string(state_value.get("name"))
    return _optional_string(payload.get("state_name") or payload.get("stateName") or state_value)


def _extract_project_identifier(payload: Mapping[str, Any]) -> str | None:
    project_value = (
        payload.get("project")
        or payload.get("project_detail")
        or payload.get("projectDetail")
        or payload.get("project_identifier")
        or payload.get("projectIdentifier")
    )
    if isinstance(project_value, Mapping):
        return _optional_string(project_value.get("identifier"))
    return _optional_string(project_value)


def _normalize_priority(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized or normalized in {"none", "no priority"}:
            return None
        if normalized.isdigit():
            return int(normalized)
        return _PLANE_PRIORITY_MAP.get(normalized)
    return None


def _normalize_labels(value: Any) -> tuple[str, ...]:
    normalized_labels: list[str] = []
    for node in _iter_nodes(value):
        if isinstance(node, str):
            label_name = _optional_string(node)
        elif isinstance(node, Mapping):
            label_name = _optional_string(node.get("name"))
        else:
            label_name = None

        if label_name is not None:
            normalized_labels.append(label_name.lower())

    return tuple(normalized_labels)


def _normalize_blocked_by(payload: Mapping[str, Any]) -> tuple[IssueBlocker, ...]:
    raw_blockers = (
        payload.get("blocked_by")
        or payload.get("blockedBy")
        or payload.get("blocked_by_issues")
        or payload.get("blockedByIssues")
    )
    blockers: list[IssueBlocker] = []

    for blocker_value in _iter_nodes(raw_blockers):
        blocker_payload = _extract_related_issue(blocker_value)
        if blocker_payload is None:
            continue

        blockers.append(
            IssueBlocker(
                id=_optional_string(blocker_payload.get("id")),
                identifier=_extract_blocker_identifier(blocker_payload),
                state=_extract_state_name(blocker_payload),
            )
        )

    return tuple(blockers)


def _extract_related_issue(value: Any) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        return None

    nested_issue = value.get("issue") or value.get("related_issue") or value.get("relatedIssue")
    if isinstance(nested_issue, Mapping):
        return nested_issue
    return value


def _extract_blocker_identifier(payload: Mapping[str, Any]) -> str | None:
    explicit_identifier = _optional_string(payload.get("identifier"))
    if explicit_identifier is not None:
        return explicit_identifier

    project_identifier = _extract_project_identifier(payload)
    sequence_id = _optional_identifier(payload.get("sequence_id") or payload.get("sequenceId"))
    if project_identifier is None or sequence_id is None:
        return None
    return f"{project_identifier}-{sequence_id}"


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _optional_identifier(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    return _optional_string(value)


def _parse_timestamp(value: Any) -> datetime | None:
    raw_value = _optional_string(value)
    if raw_value is None:
        return None

    candidate = raw_value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise PlanePayloadError(f"Plane issue payload has invalid timestamp: {raw_value}.") from exc


def _iter_nodes(value: Any) -> Iterable[Any]:
    if isinstance(value, Mapping):
        for key in ("results", "nodes"):
            nodes = value.get(key)
            if isinstance(nodes, list):
                return nodes
        return ()
    if isinstance(value, list):
        return value
    return ()


def _strip_html_description(value: str) -> str | None:
    parser = _HTMLTextExtractor()
    parser.feed(value)
    parser.close()

    raw_text = parser.get_text()
    normalized_lines = [line.strip() for line in raw_text.splitlines()]
    text = "\n".join(line for line in normalized_lines if line)
    return text or None


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "hr"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"div", "li", "p", "section", "tr"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)
