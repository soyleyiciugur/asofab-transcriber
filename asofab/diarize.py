"""Whole-recording acoustic diarization (pyannote) plus word-to-speaker assignment.

Diarization runs over the complete audio in one pass so cluster identities are global:
there are no per-chunk speaker resets.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Callable

# ------------------------------------------------------------------ execution


def run_diarization(job, settings: dict, progress: Callable[[float, str], None]) -> None:
    """Runs pyannote in a child process. A native crash (access violation, OpenMP abort, missing
    CUDA DLL) then fails this one stage with an explanation instead of killing the whole app."""
    import os
    import subprocess
    import sys
    if os.environ.get("ASOFAB_INPROC") == "1":
        return _diarize_inprocess(job, settings, progress)
    from .config import app_dir
    cmd = ([sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "asofab.main"])
    cmd += ["--diarize-worker", job.id]
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    def attempt(env_extra: dict) -> tuple[int, list[str]]:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", creationflags=flags,
                                env={**os.environ, **env_extra})
        tail: list[str] = []
        for line in proc.stdout:
            line = line.rstrip()
            if line.startswith("PROGRESS "):
                _, frac, msg = line.split(" ", 2)
                progress(float(frac), msg)
            elif line:
                tail = (tail + [line])[-25:]
        return proc.wait(), tail

    progress(0.02, "Starting diarization worker (loading models, this can take a minute)")
    code, tail = attempt({})
    if code not in (0, 1) and os.environ.get("CUDA_VISIBLE_DEVICES") != "-1":
        # Exit code 1 is an ordinary Python error (bad token, missing terms). Anything else is a
        # native crash, in practice a broken GPU/cuDNN setup. The result is the same model, only slower.
        progress(0.02, f"GPU diarization crashed (exit code {code}). Retrying on CPU: slower, same accuracy.")
        code, tail = attempt({"CUDA_VISIBLE_DEVICES": "-1"})
    if code != 0:
        hint = ""
        if code in (3221225477, -1073741819):
            hint = " (0xC0000005 access violation: a native library crashed, usually a CUDA/DLL problem.)"
        elif code in (3, 134, -6):
            hint = " (the process aborted, often an OpenMP/DLL conflict.)"
        elif code in (3221226505, -1073740791):
            hint = " (0xC0000409: native stack/DLL failure.)"
        raise RuntimeError(f"The diarization process stopped unexpectedly with exit code {code}{hint}\n"
                           + "\n".join(tail[-12:])
                           + f"\nFull log: {app_dir() / 'asofab.log'}")


def worker_main(job_id: str) -> int:
    """Child process entry: runs diarization and reports progress on stdout."""
    import traceback
    from .config import load_settings
    from .store import Job

    def progress(frac: float, msg: str) -> None:
        print(f"PROGRESS {frac:.3f} {msg}", flush=True)

    try:
        from . import hf_compat
        hf_compat.install()
        _diarize_inprocess(Job(job_id), load_settings(), progress)
        return 0
    except Exception as e:
        traceback.print_exc()
        print(f"{type(e).__name__}: {e}", flush=True)
        return 1


def _diarize_inprocess(job, settings: dict, progress: Callable[[float, str], None]) -> None:
    token = settings.get("hf_token") or None
    try:
        import torch
        from pyannote.audio import Pipeline
    except Exception as e:  # pragma: no cover
        raise RuntimeError(f"pyannote.audio is not available: {e}")
    try:
        pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=token)
    except Exception as e:
        raise RuntimeError(
            "Could not load the pyannote diarization model. You must (1) create a free Hugging Face "
            "account, (2) accept the terms on https://hf.co/pyannote/speaker-diarization-3.1 and "
            "https://hf.co/pyannote/segmentation-3.0, and (3) paste a read token in Settings. "
            f"Detail: {str(e)[:200]}")
    if pipe is None:
        raise RuntimeError("pyannote returned no pipeline. Check the Hugging Face token and accepted terms.")
    use_cuda = torch.cuda.is_available()
    if use_cuda:
        pipe.to(torch.device("cuda"))
    device = "GPU" if use_cuda else "CPU (slow: a long session can take hours)"
    progress(0.05, f"Diarizing full recording on {device}. No percentage is available until it finishes.")
    diar, emb = pipe(str(job.audio_path), min_speakers=settings.get("min_speakers", 2),
                     max_speakers=settings.get("max_speakers", 6), return_embeddings=True)
    labels = list(diar.labels())
    turns = [{"start": float(t.start), "end": float(t.end), "cluster": str(lab)}
             for t, _, lab in diar.itertracks(yield_label=True)]
    centroids = {str(lab): [float(x) for x in emb[i]] for i, lab in enumerate(labels)}
    dur = defaultdict(float)
    for t in turns:
        dur[t["cluster"]] += t["end"] - t["start"]
    job.write("diarization.json", {"turns": turns, "centroids": centroids, "durations": dict(dur),
                                   "num_clusters": len(labels), "expected_prior": settings.get("expected_speakers", 4)})
    progress(1.0, f"Diarization found {len(labels)} voice clusters")


# ---------------------------------------------------------------- pure helpers


def cosine(a, b) -> float:
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def consolidate_clusters(centroids: dict, durations: dict, expected: int = 4, minor_s: float = 45.0,
                         merge_sim: float = 0.60) -> dict:
    """Four speakers is a prior, not a rule.

    Clusters with little speech are merged into their most similar major cluster only if
    similarity is high. Otherwise they are kept and later flagged, never forced.
    Returns {cluster: merged_into_cluster}.
    """
    majors = [c for c, d in durations.items() if d >= minor_s]
    if len(majors) < 2:
        majors = sorted(durations, key=durations.get, reverse=True)[:max(2, min(expected, len(durations)))]
    mapping = {c: c for c in durations}
    if len(durations) <= expected:
        return mapping
    for c, d in durations.items():
        if c in majors:
            continue
        best, bs = None, 0.0
        for m in majors:
            s = cosine(centroids[c], centroids[m])
            if s > bs:
                best, bs = m, s
        if best is not None and bs >= merge_sim:
            mapping[c] = best
    return mapping


def _overlap(a0, a1, b0, b1) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


class TurnIndex:
    def __init__(self, turns: list[dict], cluster_map: dict | None = None):
        cm = cluster_map or {}
        self.turns = sorted(({"start": t["start"], "end": t["end"], "cluster": cm.get(t["cluster"], t["cluster"])}
                             for t in turns), key=lambda t: t["start"])
        self.starts = [t["start"] for t in self.turns]
        self.max_len = max((t["end"] - t["start"] for t in self.turns), default=0)

    def coverage(self, s: float, e: float) -> dict[str, float]:
        import bisect
        lo = bisect.bisect_left(self.starts, s - self.max_len - 1)
        res: dict[str, float] = defaultdict(float)
        for t in self.turns[lo:]:
            if t["start"] >= e:
                break
            o = _overlap(s, e, t["start"], t["end"])
            if o > 0:
                res[t["cluster"]] += o
        return res

    def nearest(self, s: float, e: float, within: float = 0.6) -> str | None:
        best, bd = None, within
        for t in self.turns:
            d = max(t["start"] - e, s - t["end"], 0.0)
            if d < bd:
                best, bd = t["cluster"], d
            if t["start"] > e + within:
                break
        return best


def assign_words(segment: dict, idx: TurnIndex) -> list[dict]:
    """Split one ASR segment into per-speaker utterances using word timings.

    Each utterance has: cluster, overlap flag, other clusters speaking at the same time,
    and the fraction of its words that diarization actually covered.
    """
    words = segment.get("words") or []
    if not words:
        cov = idx.coverage(segment["start"], segment["end"])
        cl = max(cov, key=cov.get) if cov else idx.nearest(segment["start"], segment["end"])
        others = sorted(c for c in cov if c != cl and cov[c] > 0.3 * (segment["end"] - segment["start"]))
        return [{"start": segment["start"], "end": segment["end"], "text": segment["text"], "words": [],
                 "cluster": cl, "overlap": bool(others), "overlaps_with": others, "coverage": 1.0 if cov else 0.0,
                 "lang": segment.get("lang"), "src": segment}]
    labelled = []
    for w in words:
        s, e = w["s"], max(w["e"], w["s"] + 0.01)
        cov = idx.coverage(s, e)
        total = e - s
        if cov:
            cl = max(cov, key=cov.get)
            others = [c for c, v in cov.items() if c != cl and v > 0.4 * total]
            labelled.append((w, cl, bool(others), others, cov[cl] / total))
        else:
            labelled.append((w, idx.nearest(s, e), False, [], 0.0))
    # runs
    runs: list[list] = []
    for item in labelled:
        if runs and runs[-1][0][1] == item[1]:
            runs[-1].append(item)
        else:
            runs.append([item])
    # smooth weak sandwiched runs
    changed = True
    while changed and len(runs) >= 3:
        changed = False
        for i in range(1, len(runs) - 1):
            r = runs[i]
            if runs[i - 1][0][1] == runs[i + 1][0][1] != r[0][1]:
                weak = len(r) <= 1 and (sum(x[4] for x in r) / len(r)) < 0.6
                if weak:
                    for x in r:
                        runs[i - 1].append((x[0], runs[i - 1][0][1], x[2], x[3], x[4]))
                    runs[i - 1].extend(runs[i + 1])
                    del runs[i:i + 2]
                    changed = True
                    break
    out = []
    for r in runs:
        ws = [x[0] for x in r]
        text = "".join(w["w"] for w in ws).strip()
        others = sorted({c for x in r for c in x[3]})
        out.append({"start": ws[0]["s"], "end": ws[-1]["e"], "text": text, "words": ws, "cluster": r[0][1],
                    "overlap": any(x[2] for x in r), "overlaps_with": others,
                    "coverage": sum(1 for x in r if x[4] > 0) / len(r), "lang": segment.get("lang"),
                    "src": segment})
    return out