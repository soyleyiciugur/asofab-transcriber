"""Windows without Developer Mode or admin rights cannot create symlinks (WinError 1314).
huggingface_hub's cache is built from symlinks, so model downloads fail there. Make it copy instead."""
from __future__ import annotations

import os
import shutil


def install() -> bool:
    """Returns True if the patch was applied."""
    try:
        from huggingface_hub import file_download as fd
    except Exception:
        return False
    if getattr(fd, "_asofab_patched", False):
        return True
    orig = getattr(fd, "_create_symlink", None)
    if orig is None:
        return False

    def create(src, dst, new_blob=False):
        try:
            return orig(src, dst, new_blob=new_blob)
        except OSError:
            src = str(src)
            if not os.path.isabs(src):
                src = os.path.normpath(os.path.join(os.path.dirname(str(dst)), src))
            os.makedirs(os.path.dirname(str(dst)), exist_ok=True)
            if os.path.lexists(str(dst)):
                os.remove(str(dst))
            shutil.copyfile(src, str(dst))

    fd._create_symlink = create
    if hasattr(fd, "are_symlinks_supported"):
        fd.are_symlinks_supported = lambda *a, **k: False
    fd._asofab_patched = True
    return True
