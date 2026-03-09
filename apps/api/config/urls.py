from django.http import HttpRequest, JsonResponse
from django.urls import path


def healthcheck(_request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok", "service": "symphony-api"})


urlpatterns = [
    path("healthz", healthcheck, name="healthcheck"),
]
