from __future__ import annotations

from django.http import HttpRequest, JsonResponse

from symphony.observability.runtime import RuntimeSnapshotUnavailableError, get_runtime_snapshot

ALLOWED_STATE_METHODS = "GET, HEAD"


def healthcheck(_request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok", "service": "symphony-api"})


def runtime_state(request: HttpRequest) -> JsonResponse:
    if request.method not in {"GET", "HEAD"}:
        response = _error_response(
            code="method_not_allowed",
            message=f"Method {request.method!r} is not allowed for /api/v1/state.",
            status=405,
        )
        response["Allow"] = ALLOWED_STATE_METHODS
        return response

    try:
        snapshot = get_runtime_snapshot()
    except RuntimeSnapshotUnavailableError as exc:
        return _error_response(code="unavailable", message=str(exc), status=503)
    except TimeoutError as exc:
        return _error_response(code="timeout", message=str(exc), status=503)

    return JsonResponse(snapshot)


def _error_response(*, code: str, message: str, status: int) -> JsonResponse:
    return JsonResponse(
        {"error": {"code": code, "message": message}},
        status=status,
    )
