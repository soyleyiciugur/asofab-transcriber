"""Launcher used by PyInstaller and for source runs."""
import os
import sys


def _add_bundled_dll_dirs() -> None:
    """Packaged Windows build: make the bundled NVIDIA runtime DLLs (cuBLAS, cuDNN) loadable."""
    base = getattr(sys, "_MEIPASS", None)
    if not base or sys.platform != "win32":
        return
    for root, dirs, files in os.walk(base):
        if any(f.lower().endswith(".dll") for f in files) and ("nvidia" in root.lower() or root == base):
            try:
                os.add_dll_directory(root)
            except OSError:
                pass
            os.environ["PATH"] = root + os.pathsep + os.environ.get("PATH", "")


if __name__ == "__main__":
    _add_bundled_dll_dirs()
    from asofab.main import main
    main()
