"""`ASOFAB-Transcriber.exe --selftest`: checks that every bundled piece actually loads and runs."""
from __future__ import annotations

import inspect
import subprocess


def run() -> int:
    bad = 0

    def check(name, fn):
        nonlocal bad
        try:
            detail = fn() or ""
            print(f"OK    {name} {detail}")
        except BaseException as e:  # noqa: BLE001
            bad += 1
            print(f"FAIL  {name}: {type(e).__name__}: {e}")

    from . import media

    def ff(tool):
        def f():
            exe = media._bin(tool)
            r = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                raise RuntimeError(f"{exe} exit {r.returncode}: {r.stderr[:200]}")
            return r.stdout.splitlines()[0]
        return f

    check("ffmpeg", ff("ffmpeg"))
    check("ffprobe", ff("ffprobe"))

    def imp(mod):
        def f():
            m = __import__(mod, fromlist=["x"])
            return getattr(m, "__version__", "")
        return f

    for mod in ("numpy", "soundfile", "torch", "torchaudio", "ctranslate2", "faster_whisper",
                "huggingface_hub", "pyannote.audio", "pyannote.audio.pipelines", "speechbrain",
                "google_auth_oauthlib", "keyring", "fastapi", "uvicorn", "requests"):
        check(f"import {mod}", imp(mod))

    def sig():
        from pyannote.audio import Pipeline, Model
        import huggingface_hub
        for fn in (Pipeline.from_pretrained, Model.from_pretrained):
            if "use_auth_token" not in inspect.signature(fn).parameters:
                raise RuntimeError(f"{fn} no longer accepts use_auth_token")
        return f"huggingface_hub {huggingface_hub.__version__}"
    check("pyannote auth-token argument", sig)

    def torch_rt():
        import torch
        return f"cuda={torch.cuda.is_available()}"
    check("torch runtime", torch_rt)

    print("SELFTEST " + ("FAILED" if bad else "PASSED"))
    return 1 if bad else 0
