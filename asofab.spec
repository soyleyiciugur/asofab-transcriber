# PyInstaller spec. Build with:  pyinstaller asofab.spec --noconfirm
# Expects build/bin/ffmpeg.exe and build/bin/ffprobe.exe (the CI workflow downloads them).
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

datas, binaries, hidden = [("asofab/static", "asofab/static")], [], []

for pkg in ("faster_whisper", "ctranslate2", "pyannote", "speechbrain", "lightning_fabric", "pytorch_lightning",
            "asteroid_filterbanks", "torch_audiomentations", "torchmetrics", "soundfile", "keyring",
            "google_auth_oauthlib", "uvicorn", "tokenizers", "av", "onnxruntime"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hidden += h
    except Exception:
        pass

for pkg in ("nvidia.cublas", "nvidia.cudnn", "nvidia.cuda_runtime", "nvidia.cuda_nvrtc"):
    try:
        binaries += collect_dynamic_libs(pkg)
    except Exception:
        pass

for exe in ("ffmpeg.exe", "ffprobe.exe"):
    p = Path("build/bin") / exe
    if p.exists():
        binaries.append((str(p), "bin"))

hidden += ["uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
           "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on", "keyring.backends.Windows"]

a = Analysis(["run_app.py"], pathex=["."], binaries=binaries, datas=datas, hiddenimports=hidden,
             excludes=["tkinter", "matplotlib.tests"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ASOFAB-Transcriber", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="ASOFAB-Transcriber")
