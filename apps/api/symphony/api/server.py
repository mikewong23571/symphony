from __future__ import annotations

import threading
import warnings
from dataclasses import dataclass
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

DEFAULT_HTTP_BIND_HOST = "127.0.0.1"


class ThreadedWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class QuietWSGIRequestHandler(WSGIRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return


@dataclass(slots=True)
class RuntimeHTTPServer:
    host: str
    port: int
    _server: WSGIServer
    _thread: threading.Thread

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            warnings.warn(
                "Runtime HTTP server thread did not exit within the shutdown timeout.",
                RuntimeWarning,
                stacklevel=2,
            )


def start_runtime_http_server(
    *,
    host: str = DEFAULT_HTTP_BIND_HOST,
    port: int,
) -> RuntimeHTTPServer:
    from config.wsgi import application

    server = make_server(
        host,
        port,
        application,
        server_class=ThreadedWSGIServer,
        handler_class=QuietWSGIRequestHandler,
    )
    thread = threading.Thread(
        target=server.serve_forever,
        name="symphony-runtime-http",
        daemon=True,
    )
    thread.start()
    return RuntimeHTTPServer(
        host=host,
        port=server.server_port,
        _server=server,
        _thread=thread,
    )
