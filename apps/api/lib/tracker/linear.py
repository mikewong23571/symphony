from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from .models import Issue, IssueBlocker


class LinearPayloadError(Exception):
    code = "linear_unknown_payload"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def normalize_linear_issue(payload: Mapping[str, Any]) -> Issue:
    issue_id = _require_string(payload, "id")
    identifier = _require_string(payload, "identifier")
    title = _require_string(payload, "title")
    state = _extract_state_name(payload.get("state"))
    if state is None:
        raise LinearPayloadError("Linear issue payload is missing state.name.")

    return Issue(
        id=issue_id,
        identifier=identifier,
        title=title,
        description=_optional_string(payload.get("description")),
        priority=_normalize_priority(payload.get("priority")),
        state=state,
        branch_name=_optional_string(payload.get("branchName") or payload.get("branch_name")),
        url=_optional_string(payload.get("url")),
        labels=_normalize_labels(payload.get("labels")),
        blocked_by=_normalize_blocked_by(payload.get("inverseRelations")),
        created_at=_parse_timestamp(payload.get("createdAt") or payload.get("created_at")),
        updated_at=_parse_timestamp(payload.get("updatedAt") or payload.get("updated_at")),
    )


def _require_string(payload: Mapping[str, Any], key: str) -> str:
    value = _optional_string(payload.get(key))
    if value is None:
        raise LinearPayloadError(f"Linear issue payload is missing {key}.")
    return value


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _extract_state_name(value: Any) -> str | None:
    if isinstance(value, Mapping):
        return _optional_string(value.get("name"))
    return _optional_string(value)


def _normalize_priority(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return int(value)


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


def _normalize_blocked_by(value: Any) -> tuple[IssueBlocker, ...]:
    blockers: list[IssueBlocker] = []
    for relation in _iter_nodes(value):
        if not isinstance(relation, Mapping):
            continue

        relation_type = _optional_string(relation.get("type"))
        if relation_type is None or relation_type.lower() != "blocks":
            continue

        related_issue = relation.get("issue")
        if not isinstance(related_issue, Mapping):
            related_issue = relation.get("relatedIssue")
        if not isinstance(related_issue, Mapping):
            continue

        blockers.append(
            IssueBlocker(
                id=_optional_string(related_issue.get("id")),
                identifier=_optional_string(related_issue.get("identifier")),
                state=_extract_state_name(related_issue.get("state")),
            )
        )

    return tuple(blockers)


def _parse_timestamp(value: Any) -> datetime | None:
    raw_value = _optional_string(value)
    if raw_value is None:
        return None

    candidate = raw_value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise LinearPayloadError(
            f"Linear issue payload has invalid timestamp: {raw_value}."
        ) from exc


def _iter_nodes(value: Any) -> Iterable[Any]:
    if isinstance(value, Mapping):
        nodes = value.get("nodes")
        if isinstance(nodes, list):
            return nodes
        return ()
    if isinstance(value, list):
        return value
    return ()
