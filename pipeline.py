"""FFprobe inspection and audio extraction. Never modifies the source file."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def _bin(name: str) -> str:
    # Bundled binaries (PyInstaller) live next to the executable in ./bin
    candidates = []
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else Path(sys.executable).parent
        candidates += [base / "bin" / f"{name}.exe", base / f"{name}.exe"]
    for c in candidates:
        if c.exists():
            return str(c)
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f"{name} not found. The packaged app bundles it; for source runs install FFmpeg.")
    return found


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          creationflags=flags)


def probe(path: Path) -> dict:
    r = _run([_bin("ffprobe"), "-v", "error", "-print_format", "json", "-show_format",
              "-show_streams", "-show_chapters", str(path)])
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {r.stderr.strip()[:300]}")
    return json.loads(r.stdout)


def summarize_probe(info: dict) -> dict:
    """Plain-language findings about what the file genuinely contains."""
    streams = info.get("streams", [])
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    video = [s for s in streams if s.get("codec_type") == "video"]
    subs = [s for s in streams if s.get("codec_type") == "subtitle"]
    fmt = info.get("format", {})
    tags = {**fmt.get("tags", {})}
    notes = []
    separate_tracks = len(audio) > 1
    if separate_tracks:
        notes.append(f"{len(audio)} audio streams found. They may be separate tracks, "
                     "but this is only used if stream metadata marks them as distinct speakers.")
    else:
        ch = audio[0].get("channels") if audio else None
        notes.append("Single mixed audio stream."
                     + (f" It has {ch} channels, which are NOT treated as separate people." if ch and ch > 1 else ""))
    if subs:
        notes.append(f"{len(subs)} subtitle stream(s) present.")
    participant_tags = {k: v for k, v in tags.items()
                        if any(w in k.lower() for w in ("participant", "speaker", "attendee"))}
    for i, a in enumerate(audio):
        for k, v in (a.get("tags") or {}).items():
            if any(w in k.lower() for w in ("participant", "speaker", "attendee")):
                participant_tags[f"audio{i}.{k}"] = v
    if participant_tags:
        notes.append("Embedded participant-related metadata present.")
    else:
        notes.append("No participant-related metadata is embedded in the file.")
    return {
        "duration_s": float(fmt.get("duration", 0) or 0),
        "container": fmt.get("format_name"),
        "audio_streams": [{"index": a.get("index"), "codec": a.get("codec_name"),
                           "channels": a.get("channels"), "sample_rate": a.get("sample_rate"),
                           "tags": a.get("tags", {})} for a in audio],
        "video_streams": [{"index": v.get("index"), "codec": v.get("codec_name"),
                           "width": v.get("width"), "height": v.get("height"),
                           "fps": v.get("r_frame_rate")} for v in video],
        "subtitle_streams": len(subs),
        "participant_metadata": participant_tags,
        "has_separate_audio_tracks": separate_tracks and bool(participant_tags),
        "notes": notes,
    }


def extract_audio(src: Path, dest: Path, stream_index: int | None = None) -> Path:
    """Mono 16 kHz PCM WAV (the format Whisper/pyannote expect). Mixes channels equally."""
    cmd = [_bin("ffmpeg"), "-y", "-v", "error", "-i", str(src)]
    cmd += ["-map", f"0:{stream_index}" if stream_index is not None else "0:a:0"]
    cmd += ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dest)]
    r = _run(cmd)
    if r.returncode != 0 or not dest.exists():
        raise RuntimeError(f"Audio extraction failed: {r.stderr.strip()[:300]}")
    return dest


def cut_clip(wav: Path, dest: Path, start: float, end: float) -> Path:
    r = _run([_bin("ffmpeg"), "-y", "-v", "error", "-ss", f"{max(0, start):.3f}",
              "-to", f"{end:.3f}", "-i", str(wav), "-c:a", "libmp3lame", "-q:a", "4", str(dest)])
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:200])
    return dest
