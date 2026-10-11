import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    """Every test gets its own data directory."""
    d = tmp_path / "home"
    monkeypatch.setenv("ASOFAB_HOME", str(d))
    monkeypatch.delenv("ASOFAB_ALLOW_LOCAL", raising=False)
    return d


@pytest.fixture
def mixed_stereo_mp4(tmp_path):
    """A real mixed-stereo MP4 (one AAC stream, 2 channels), like a Meet recording."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    out = tmp_path / "rec.mp4"
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "sine=frequency=300:duration=6",
         "-f", "lavfi", "-i", "sine=frequency=500:duration=6",
         "-f", "lavfi", "-i", "color=c=black:s=160x90:d=6",
         "-filter_complex", "[0:a][1:a]amerge=inputs=2[a]",
         "-map", "[a]", "-map", "2:v", "-c:a", "aac", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-shortest", str(out)],
        capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        pytest.skip(f"could not build test video: {r.stderr[:200]}")
    return out
