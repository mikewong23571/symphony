from __future__ import annotations

import json
from urllib.request import urlopen

from symphony.api.server import start_runtime_http_server


def test_start_runtime_http_server_serves_wsgi_requests_and_closes_cleanly() -> None:
    server = start_runtime_http_server(port=0)
    try:
        with urlopen(f"{server.url}healthz", timeout=5) as response:
            assert response.status == 200
            assert json.loads(response.read().decode("utf-8")) == {
                "status": "ok",
                "service": "symphony-api",
            }
    finally:
        server.close()

    assert not server._thread.is_alive()
