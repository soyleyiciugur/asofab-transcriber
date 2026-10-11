"""Optional, conservative IC/OOC labelling. Everything it produces is editable and marked auto.

It only commits to OOC on strong rules/meta cues. GM narration needs a GM speaker, a long
utterance and no meta cues. Everything else stays '[Uncertain IC/OOC]'.
"""
from __future__ import annotations

import re

OOC_CUES = re.compile(
    r"\b(zar|roll|kural|rule|hasar|damage|tier|cost|maliyet|kart|deck|deste|draw|buff|ability|trait|"
    r"influence|power|command|military|political|royal favor|chronicle|ledger|bir dakika|sekiz|"
    r"bakıyorum|bakayım|pause|mola|ses|mikrofon|duyuyor musun|discord|meet|kayıt)\b", re.I)
LAUGH = re.compile(r"\b(ha ha|hahaha|haha|lol|kahkaha|\(laughs\)|\[laughter\])\b", re.I)


def classify(seg: dict) -> tuple[str, str]:
    t = seg["text"]
    words = len(t.split())
    is_gm = seg.get("speaker") == "Hasan"
    if OOC_CUES.search(t) or LAUGH.search(t):
        return "OOC", "auto"
    if is_gm and words >= 25:
        return "GM Narration", "auto"
    return "Uncertain IC/OOC", "auto"


def annotate(segments: list[dict]) -> None:
    for s in segments:
        if s.get("ic_ooc_source") == "user":
            continue
        s["ic_ooc"], s["ic_ooc_source"] = classify(s)
