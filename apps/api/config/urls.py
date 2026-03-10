from django.urls import path
from symphony.api.views import healthcheck, runtime_issue, runtime_refresh, runtime_state

urlpatterns = [
    path("healthz", healthcheck, name="healthcheck"),
    path("api/v1/state", runtime_state, name="runtime-state"),
    path("api/v1/refresh", runtime_refresh, name="runtime-refresh"),
    path("api/v1/<str:issue_identifier>", runtime_issue, name="runtime-issue"),
]
