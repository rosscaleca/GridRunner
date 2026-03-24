"""GridRunner desktop entry point.

Starts the FastAPI server in a background thread and opens
a native OS webview window via pywebview.
"""

import os
import socket
import threading
import time

import httpx
import uvicorn
import webview


def find_free_port() -> int:
    """Find an available port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_server(port: int, timeout: float = 10.0) -> None:
    """Poll the health endpoint until the server is ready."""
    url = f"http://127.0.0.1:{port}/health"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(url, timeout=1.0)
            if resp.status_code == 200:
                return
        except httpx.ConnectError:
            pass
        time.sleep(0.1)
    raise TimeoutError(f"Server did not start within {timeout}s")


class JsApi:
    """Python API exposed to the frontend via window.pywebview.api."""

    def __init__(self, window_ref):
        self._window_ref = window_ref

    def browse_file(self, file_types=None):
        """Open a native file picker and return the selected path."""
        result = self._window_ref().create_file_dialog(
            webview.OPEN_DIALOG,
            file_types=file_types or ("All files (*.*)",),
        )
        if result and len(result) > 0:
            return result[0]
        return None

    def browse_directory(self):
        """Open a native folder picker and return the selected path."""
        result = self._window_ref().create_file_dialog(
            webview.FOLDER_DIALOG,
        )
        if result and len(result) > 0:
            return result[0]
        return None


def main() -> None:
    port = find_free_port()

    # Set port before importing backend (config reads env at import time)
    os.environ["GRIDRUNNER_PORT"] = str(port)

    from backend.main import app

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)

    # Run uvicorn in a daemon thread (its own asyncio loop)
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    wait_for_server(port)

    # Use a mutable container so JsApi can reference the window after creation
    window_holder = []
    js_api = JsApi(lambda: window_holder[0])

    # pywebview owns the main thread (native GUI event loop)
    window = webview.create_window(
        "GridRunner",
        url=f"http://127.0.0.1:{port}",
        width=1200,
        height=800,
        resizable=True,
        min_size=(800, 600),
        js_api=js_api,
    )
    window_holder.append(window)
    webview.start()

    # Window closed — shut down server
    server.should_exit = True
    server_thread.join(timeout=3)


if __name__ == "__main__":
    main()
