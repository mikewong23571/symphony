from django.urls import path
from symphony.api.views import (
    healthcheck,
    runtime_dashboard,
    runtime_issue,
    runtime_refresh,
    runtime_state,
    tracker_comment,
    tracker_pull_request,
    tracker_transition,
)

urlpatterns = [
    path("", runtime_dashboard, name="runtime-dashboard"),
    path("healthz", healthcheck, name="healthcheck"),
    path("api/v1/state", runtime_state, name="runtime-state"),
    path("api/v1/refresh", runtime_refresh, name="runtime-refresh"),
    path(
        "api/v1/tracker/issues/<str:issue_identifier>/comments",
        tracker_comment,
        name="tracker-comment",
    ),
    path(
        "api/v1/tracker/issues/<str:issue_identifier>/transition",
        tracker_transition,
        name="tracker-transition",
    ),
    path(
        "api/v1/tracker/issues/<str:issue_identifier>/pull-request",
        tracker_pull_request,
        name="tracker-pull-request",
    ),
    path("api/v1/<str:issue_identifier>", runtime_issue, name="runtime-issue"),
]
