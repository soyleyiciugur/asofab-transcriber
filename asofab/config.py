"""Paths, model policy and settings. Stored under %LOCALAPPDATA%/ASOFAB (Windows) or ~/.asofab."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def app_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    d = Path(os.environ.get("ASOFAB_HOME", base / "ASOFAB"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def jobs_dir() -> Path:
    d = app_dir() / "jobs"
    d.mkdir(exist_ok=True)
    return d


def models_dir() -> Path:
    d = app_dir() / "models"
    d.mkdir(exist_ok=True)
    return d


def glossary_path() -> Path:
    return app_dir() / "glossary.json"


def settings_path() -> Path:
    return app_dir() / "settings.json"


DEFAULT_SETTINGS = {
    # Accuracy policy: the app never silently drops to a worse model.
    "asr_model": "large-v3",
    "allow_smaller_model": False,
    "hf_token": "",              # needed once to accept pyannote terms
    "cloud_transcription_consent": False,  # always off by default
    "delete_temp_audio_after": False,
    "expected_speakers": 4,
    "min_speakers": 2,
    "max_speakers": 6,
}


def load_settings() -> dict:
    p = settings_path()
    s = dict(DEFAULT_SETTINGS)
    if p.exists():
        try:
            s.update(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return s


def save_settings(s: dict) -> None:
    settings_path().write_text(json.dumps(s, indent=2), encoding="utf-8")
