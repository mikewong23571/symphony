from __future__ import annotations

from symphony.workflow import ServiceConfig
from symphony.workflow.config import require_linear_tracker_config

from .interfaces import TrackerMutationBackend, TrackerReadClient
from .linear_client import LinearTrackerClient


def build_tracker_read_client(config: ServiceConfig) -> TrackerReadClient:
    return _build_tracker_client(config)


def build_tracker_mutation_backend(config: ServiceConfig) -> TrackerMutationBackend:
    return _build_tracker_client(config)


def _build_tracker_client(config: ServiceConfig) -> LinearTrackerClient:
    return LinearTrackerClient(require_linear_tracker_config(config.tracker))
