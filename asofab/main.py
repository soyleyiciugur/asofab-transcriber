"""Entry point: starts the local server and opens the UI in the default browser."""
from __future__ import annotations

import os
import sys

# torch and ctranslate2 (faster-whisper) each ship an OpenMP runtime. When both load in one
# Windows process the second one aborts the whole process ("OMP: Error #15"), which looks like
# the app silently vanishing. Must be set before either library is imported.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import socket
import threading
import time
import webbrowser


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _enable_crash_log():
    """Write Python tracebacks AND hard native crashes (access violations) to a log file."""
    import faulthandler
    from .config import app_dir
    path = app_dir() / "asofab.log"
    try:
        f = open(path, "a", buffering=1, encoding="utf-8")
        f.write(f"\n===== start {time.strftime('%Y-%m-%d %H:%M:%S')} pid={os.getpid()} argv={sys.argv[1:]} =====\n")
        faulthandler.enable(file=f, all_threads=True)
        globals()["_log_file"] = f  # keep it open for the life of the process
    except Exception:
        pass
    return path


def main() -> None:
    log_path = _enable_crash_log()
    if len(sys.argv) >= 3 and sys.argv[1] == "--diarize-worker":
        from .diarize import worker_main
        sys.exit(worker_main(sys.argv[2]))
    try:
        _serve(log_path)
    except BaseException:
        import traceback
        traceback.print_exc()
        print(f"\nASOFAB crashed. Details are in: {log_path}")
        if getattr(sys, "frozen", False):
            input("Press Enter to close this window...")
        raise


def _serve(log_path) -> None:
    import uvicorn
    from . import hf_compat
    hf_compat.install()
    from .server import app
    port = int(os.environ.get("ASOFAB_PORT") or 0) or free_port()  # fixed port is for the CI smoke test
    url = f"http://127.0.0.1:{port}/"
    if os.environ.get("ASOFAB_NO_BROWSER") != "1":
        threading.Thread(target=lambda: (time.sleep(1.2), webbrowser.open(url)), daemon=True).start()
    print(f"ASOFAB Transcriber running at {url}  (close this window to quit)")
    print(f"Log file: {log_path}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()