"""Export formats. The reading view has no timestamps; they stay in JSON/CSV/SRT."""
from __future__ import annotations

import csv
import io
import json

from .store import UNKNOWN

ANCHOR = "21/8/99 AC: Vhaemys claimed a dragon."


def ts(sec: float, sep: str = ",") -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def _tag(s: dict, include_ic: bool) -> str:
    tags = []
    if include_ic and s.get("ic_ooc") and s["ic_ooc"] != "":
        tags.append(s["ic_ooc"])
    if s.get("overlap"):
        tags.append("overlapping")
    return "".join(f" [{t}]" for t in tags)


def _text(s: dict) -> str:
    t = s["text"].strip()
    if s.get("review_open") and "[to be checked]" not in t:
        t += " [to be checked]"
    return t


def full_transcript_md(segments: list[dict], include_ic: bool = True, title: str = "ASOFAB Full Transcript") -> str:
    lines = [f"# {title}", ""]
    prev = None  # (label, tag, overlap)
    buf: list[str] = []
    cur_head = ""

    def flush():
        if buf:
            lines.append(f"{cur_head} {' '.join(buf)}")
            lines.append("")

    for s in sorted(segments, key=lambda x: (x["start"], x["end"])):
        label = s.get("label") or UNKNOWN
        head = f"**{label}{_tag(s, include_ic)}:**"
        key = (label, _tag(s, include_ic))
        if prev == key and not s.get("overlap") and not buf_overlap(s):
            buf.append(_text(s))
        else:
            flush()
            buf.clear()
            buf.append(_text(s))
            cur_head = head
            prev = key
    flush()
    return "\n".join(lines).rstrip() + "\n"


def buf_overlap(s: dict) -> bool:
    return bool(s.get("overlap"))


def review_csv(items: list[dict]) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["Review ID", "Speaker", "Previous line", "Uncertain line", "Next line", "Reason",
                "Candidate alternatives", "Source timestamp", "Status", "Corrected text"])
    for r in items:
        w.writerow([r["id"], r["speaker"], r["previous"], r["uncertain"], r["next"], r["issue"],
                    " | ".join(r["alternatives"]), f"{ts(r['start'], '.')} - {ts(r['end'], '.')}",
                    r["status"], r.get("corrected_text", "")])
    return "\ufeff" + out.getvalue()  # BOM so Excel on Windows reads Turkish characters


def transcript_json(job_meta: dict, segments: list[dict], review: list[dict], speakers: dict) -> str:
    data = {
        "source": {"link": job_meta.get("link"), "link_info": job_meta.get("link_info"),
                   "evidence_available": job_meta.get("evidence")},
        "speakers": {"clusters": speakers.get("clusters"), "decisions": speakers.get("decisions")},
        "segments": [{
            "id": s["id"], "start": round(s["start"], 3), "end": round(s["end"], 3),
            "speaker": s.get("speaker"), "label": s.get("label"), "cluster": s.get("cluster"),
            "text": s["text"], "text_asr": s.get("text_asr"), "language": s.get("lang"),
            "language_guess": s.get("lang_guess"), "ic_ooc": s.get("ic_ooc"),
            "ic_ooc_source": s.get("ic_ooc_source"),
            "overlap": s.get("overlap", False), "overlaps_with": s.get("overlaps_with", []),
            "asr_avg_logprob": s.get("avg_logprob"),
            "word_probabilities": [{"w": w["w"], "s": round(w["s"], 3), "e": round(w["e"], 3),
                                    "p": round(w.get("p", 0), 3)} for w in s.get("words", [])],
            "alternatives": s.get("alternatives", []),
            "speaker_confidence": s.get("speaker_confidence"), "speaker_confirmed": s.get("speaker_confirmed"),
            "speaker_conflict": s.get("conflict", False), "attribution_evidence": s.get("evidence", []),
            "user_edited": s.get("user_edited", False), "needs_review": s.get("review_open", False),
        } for s in segments],
        "review": review,
    }
    return json.dumps(data, ensure_ascii=False, indent=1)


def srt(segments: list[dict]) -> str:
    out = []
    for i, s in enumerate(sorted(segments, key=lambda x: x["start"]), 1):
        out.append(f"{i}\n{ts(s['start'])} --> {ts(max(s['end'], s['start'] + 0.3))}\n"
                   f"{s.get('label') or UNKNOWN}: {_text(s)}\n")
    return "\n".join(out)


def chapter_source_md(segments: list[dict]) -> str:
    segs = sorted(segments, key=lambda x: x["start"])
    ic = [s for s in segs if s.get("ic_ooc") in ("IC", "GM Narration")]
    ooc = [s for s in segs if s.get("ic_ooc") == "OOC"]
    unk = [s for s in segs if s.get("ic_ooc") not in ("IC", "GM Narration", "OOC")]

    def fmt(s):
        kind = "[GM Narration] " if s.get("ic_ooc") == "GM Narration" else ""
        return f"**{s.get('label') or UNKNOWN}:** {kind}{_text(s)}"

    lines = ["# ASOFAB Chapter Source", "",
             "_Source material only. No chapter has been written._", "",
             f"**Continuity anchor (background, not evidence of events in this recording):** {ANCHOR}", "",
             "## In-character dialogue and GM narration (chronological)", ""]
    lines += [fmt(s) + "\n" for s in ic] or ["_None classified yet. Classify segments as IC or GM Narration in the editor._", ""]
    lines += ["## Out-of-character context", ""]
    lines += [fmt(s) + "\n" for s in ooc] or ["_None._", ""]
    lines += ["## Unclassified (needs an IC/OOC decision)", ""]
    lines += [fmt(s) + "\n" for s in unk] or ["_None._", ""]
    return "\n".join(lines)
