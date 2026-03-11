from __future__ import annotations

from symphony.workflow import LinearTrackerConfig, ServiceConfig

from .interfaces import TrackerMutationBackend, TrackerReadClient
from .linear_client import LinearTrackerClient


def build_tracker_read_client(config: ServiceConfig) -> TrackerReadClient:
    return _build_tracker_client(config)


def build_tracker_mutation_backend(config: ServiceConfig) -> TrackerMutationBackend:
    return _build_tracker_client(config)


def _build_tracker_client(config: ServiceConfig) -> LinearTrackerClient:
    tracker = config.tracker
    if isinstance(tracker, LinearTrackerConfig) and tracker.kind == "linear":
        return LinearTrackerClient(tracker)
    raise ValueError(f"Unsupported tracker kind for adapter factory: {tracker.kind!r}.")
