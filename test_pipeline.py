"""Per-job persistent state. Every stage writes its output atomically so any failure is resumable."""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from .config import jobs_dir

STAGES = [
    "resolve",      # parse link, find conference record / Drive file, native metadata
    "download",     # authorised Drive download into a temporary local cache (resumable)
    "inspect",      # ffprobe of the real file
    "extract",      # mono 16 kHz audio for ASR/diarization
    "asr",          # VAD + chunked multilingual ASR
    "diarize",      # global acoustic diarization
    "attribute",    # merge evidence, map to people
    "vocab",        # conservative glossary application
    "recheck",      # boundaries, suspicious words, speaker flips
    "draft",        # build segments + review list
]

PEOPLE = {
    "Hasan": {"role": "GM", "label": "GM (Haso)", "names": ["hasan", "haso", "hrrm"]},
    "Uğur": {"role": "Jace", "label": "Jace (Uğur)", "names": ["uğur", "ugur"]},
    "Ulaç": {"role": "Visenor / Arthur Sand", "label": "Visenor (Ulaç)", "names": ["ulaç", "ulaş", "ulac", "ulas", "ubeka"]},
    "Taylan": {"role": "Gaelor", "label": "Gaelor (Taylan)", "names": ["taylan", "tay"]},
}
UNKNOWN = "Unknown Speaker [to be checked]"


def atomic_write(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


class Job:
    def __init__(self, job_id: str):
        self.id = job_id
        self.dir = jobs_dir() / job_id
        self.dir.mkdir(parents=True, exist_ok=True)

    # ---- creation / lookup
    @classmethod
    def create(cls, link: str) -> "Job":
        jid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        j = cls(jid)
        j.save_meta({"id": jid, "link": link, "created": time.time(),
                     "stages": {s: {"status": "pending"} for s in STAGES},
                     "evidence": {}, "link_info": {}})
        return j

    @classmethod
    def list_all(cls) -> list[dict]:
        out = []
        for p in sorted(jobs_dir().iterdir(), reverse=True):
            m = p / "job.json"
            if m.exists():
                try:
                    d = json.loads(m.read_text(encoding="utf-8"))
                    out.append({"id": d["id"], "link": d.get("link"), "created": d.get("created"),
                                "stages": {k: v.get("status") for k, v in d.get("stages", {}).items()}})
                except Exception:
                    pass
        return out

    # ---- generic json files
    def _p(self, name: str) -> Path:
        return self.dir / name

    def read(self, name: str, default: Any = None) -> Any:
        p = self._p(name)
        if not p.exists():
            return default
        return json.loads(p.read_text(encoding="utf-8"))

    def write(self, name: str, data: Any) -> None:
        atomic_write(self._p(name), data)

    # ---- meta + stage state
    def meta(self) -> dict:
        return self.read("job.json", {})

    def save_meta(self, m: dict) -> None:
        self.write("job.json", m)

    def set_stage(self, stage: str, status: str, **extra) -> None:
        m = self.meta()
        st = m["stages"].setdefault(stage, {})
        st.update(status=status, **extra)
        st["updated"] = time.time()
        self.save_meta(m)

    def stage_status(self, stage: str) -> str:
        return self.meta().get("stages", {}).get(stage, {}).get("status", "pending")

    def update_meta(self, **kv) -> None:
        m = self.meta()
        m.update(kv)
        self.save_meta(m)

    def add_evidence(self, key: str, value: Any) -> None:
        m = self.meta()
        m.setdefault("evidence", {})[key] = value
        self.save_meta(m)

    # ---- partial progress for long stages (ASR chunks)
    def chunk_path(self, kind: str, idx: int) -> Path:
        d = self.dir / kind
        d.mkdir(exist_ok=True)
        return d / f"{idx:04d}.json"

    # ---- convenience
    @property
    def audio_path(self) -> Path:
        return self.dir / "audio_16k.wav"

    @property
    def source_path(self) -> Path:
        return self.dir / "source_recording"

    def segments(self) -> list[dict]:
        return self.read("segments.json", [])

    def save_segments(self, segs: list[dict]) -> None:
        self.write("segments.json", segs)

    def review(self) -> list[dict]:
        return self.read("review.json", [])

    def save_review(self, items: list[dict]) -> None:
        self.write("review.json", items)

    def speakers(self) -> dict:
        return self.read("speakers.json", {"clusters": {}, "assignments": {}, "samples": []})

    def save_speakers(self, s: dict) -> None:
        self.write("speakers.json", s)
