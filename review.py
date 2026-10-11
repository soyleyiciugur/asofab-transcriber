"""Entry point: starts the local server and opens the UI in the default browser."""
from __future__ import annotations

import os
import socket
import threading
import time
import webbrowser


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    import uvicorn
    from .server import app
    port = int(os.environ.get("ASOFAB_PORT") or 0) or free_port()  # fixed port is for the CI smoke test
    url = f"http://127.0.0.1:{port}/"
    if os.environ.get("ASOFAB_NO_BROWSER") != "1":
        threading.Thread(target=lambda: (time.sleep(1.2), webbrowser.open(url)), daemon=True).start()
    print(f"ASOFAB Transcriber running at {url}  (close this window to quit)")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
