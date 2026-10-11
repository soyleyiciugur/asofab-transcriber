"""Builds the 'To Be Checked' list from segment flags, and applies user resolutions."""
from __future__ import annotations

from .store import UNKNOWN

KIND_TEXT = {
    "unintelligible": "Low-confidence or unintelligible words",
    "speaker_uncertain": "Speaker identity uncertain",
    "speaker_conflict": "Conflicting speaker evidence",
    "competing_asr": "Competing ASR interpretations",
    "overlap": "Overlapping or muffled speech",
    "ambiguous_name": "Possible ASOFAB name (spoken form is also an ordinary word)",
    "spelling": "Inconsistent spelling of a known name",
    "suspected_omission": "Speech detected but no text was produced (possible omission)",
    "speaker_flip": "Very short utterance between turns of another speaker (possible mislabel)",
    "boundary": "Near a processing-chunk boundary (check for duplicated/missing audio)",
}


def segment_kinds(s: dict, prev: dict | None, nxt: dict | None) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    words = s.get("words") or []
    low = [w for w in words if w.get("p", 1.0) < 0.35]
    if "[unintelligible" in s["text"].lower() or (words and len(low) / len(words) > 0.4) or \
            (s.get("avg_logprob") or 0) < -1.3:
        detail = ", ".join(w["w"].strip() for w in low[:6]) or "overall low confidence"
        out.append(("unintelligible", f"Low-probability words: {detail}"))
    if s.get("conflict"):
        out.append(("speaker_conflict", "Voice evidence disagrees: candidates "
                    + " / ".join(s.get("candidates", []))))
    elif s.get("speaker") is None:
        out.append(("speaker_uncertain", "No sufficient identity evidence for this voice."))
    if s.get("alternatives"):
        out.append(("competing_asr", "A second decoding pass produced different text."))
    if s.get("overlap") and (s.get("avg_logprob") or 0) < -0.7:
        out.append(("overlap", "Simultaneous speech with weak recognition: "
                    + ", ".join(s.get("overlaps_with", []))))
    for f in s.get("glossary_flags", []):
        out.append(("ambiguous_name", f"'{f['word']}' may be '{f['suggest']}'"))
    for old, new in s.get("spelling_variants", []):
        out.append(("spelling", f"'{old}' resembles '{new}'"))
    if prev and nxt and len(words) <= 2 and (s["end"] - s["start"]) < 0.8 and \
            prev.get("cluster") == nxt.get("cluster") != s.get("cluster"):
        out.append(("speaker_flip", "Short utterance with a different speaker label than both neighbours."))
    if s.get("boundary"):
        out.append(("boundary", KIND_TEXT["boundary"]))
    return out


def build_review(segments: list[dict], omissions: list[dict]) -> list[dict]:
    items = []
    n = 0
    for i, s in enumerate(segments):
        prev = segments[i - 1] if i else None
        nxt = segments[i + 1] if i + 1 < len(segments) else None
        kinds = segment_kinds(s, prev, nxt)
        s["review_open"] = False
        if not kinds:
            continue
        n += 1
        s["review_open"] = True
        alts = [a["text"] for a in s.get("alternatives", [])]
        for f in s.get("glossary_flags", []):
            alts.append(f["suggest"])
        items.append({
            "id": f"R{n:04d}", "seg_id": s["id"], "kinds": [k for k, _ in kinds],
            "issue": "; ".join(d for _, d in kinds),
            "speaker": s.get("label", UNKNOWN), "start": s["start"], "end": s["end"],
            "previous": prev["text"] if prev else "", "uncertain": s["text"],
            "next": nxt["text"] if nxt else "", "alternatives": alts,
            "status": "open", "corrected_text": "", "corrected_speaker": ""})
    for o in omissions:
        n += 1
        # attach context from the nearest segments
        before = [s for s in segments if s["end"] <= o["start"]]
        after = [s for s in segments if s["start"] >= o["end"]]
        items.append({
            "id": f"R{n:04d}", "seg_id": None, "kinds": ["suspected_omission"],
            "issue": f"{KIND_TEXT['suspected_omission']} ({o['end'] - o['start']:.1f}s, voice {o['cluster']})",
            "speaker": UNKNOWN, "start": o["start"], "end": o["end"],
            "previous": before[-1]["text"] if before else "", "uncertain": "[to be checked]",
            "next": after[0]["text"] if after else "", "alternatives": [], "status": "open",
            "corrected_text": "", "corrected_speaker": ""})
    items.sort(key=lambda r: r["start"])
    return items


def find_omissions(turns: list[dict], segments: list[dict], min_gap: float = 2.0) -> list[dict]:
    """Diarized speech with no ASR text over it for at least min_gap seconds."""
    spans = sorted((s["start"], s["end"]) for s in segments)
    res = []
    for t in turns:
        cur = t["start"]
        for a, b in spans:
            if b <= cur:
                continue
            if a >= t["end"]:
                break
            if a - cur >= min_gap:
                res.append({"start": cur, "end": a, "cluster": t["cluster"]})
            cur = max(cur, b)
        if t["end"] - cur >= min_gap:
            res.append({"start": cur, "end": t["end"], "cluster": t["cluster"]})
    # merge near-duplicates caused by overlapping turns
    res.sort(key=lambda r: r["start"])
    merged: list[dict] = []
    for r in res:
        if merged and r["start"] < merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], r["end"])
        else:
            merged.append(dict(r))
    return merged


def resolve(job, review_id: str, text: str | None, speaker: str | None, status: str = "resolved") -> dict:
    """Apply a user's correction to the review item AND the underlying segment."""
    items = job.review()
    segs = job.segments()
    item = next((i for i in items if i["id"] == review_id), None)
    if item is None:
        raise KeyError(review_id)
    item["status"] = status
    if text is not None:
        item["corrected_text"] = text
    if speaker is not None:
        item["corrected_speaker"] = speaker
    seg = next((s for s in segs if s["id"] == item["seg_id"]), None) if item["seg_id"] else None
    if seg is None and status == "resolved" and text:
        # omission: insert a new user-authored segment
        new = {"id": f"S{len(segs) + 1:05d}u", "start": item["start"], "end": item["end"], "text": text,
               "cluster": None, "speaker": speaker or None, "label": speaker or UNKNOWN,
               "speaker_confidence": 1.0 if speaker else 0.0, "speaker_confirmed": bool(speaker),
               "evidence": [{"source": "user_confirmed"}], "words": [], "lang": None,
               "ic_ooc": "Uncertain IC/OOC", "ic_ooc_source": "none", "review_open": False,
               "user_edited": True, "overlap": False, "overlaps_with": []}
        segs.append(new)
        segs.sort(key=lambda s: s["start"])
    elif seg is not None:
        if text is not None and text != seg["text"]:
            seg["text"] = text
            seg["user_edited"] = True
        if speaker:
            from .store import PEOPLE
            seg["speaker"] = speaker if speaker in PEOPLE else None
            seg["label"] = PEOPLE[speaker]["label"] if speaker in PEOPLE else speaker
            seg["speaker_confirmed"] = True
            seg["speaker_confidence"] = 1.0
            seg["conflict"] = False
            seg["evidence"] = [{"source": "user_confirmed", "person": speaker}]
        seg["review_open"] = status != "resolved" and seg.get("review_open", False)
        if status == "resolved":
            seg["review_open"] = False
    job.save_review(items)
    job.save_segments(segs)
    return item
