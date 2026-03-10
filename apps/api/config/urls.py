from django.urls import path
from symphony.api.views import healthcheck, runtime_state

urlpatterns = [
    path("healthz", healthcheck, name="healthcheck"),
    path("api/v1/state", runtime_state, name="runtime-state"),
]
