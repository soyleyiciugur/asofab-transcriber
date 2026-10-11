"""Multi-source speaker attribution with provenance.

Hierarchy (strongest first):
  1. user_confirmed   - explicit user assignment of a voice cluster or segment
  2. native_meet      - Meet transcript entries joined to participant records, aligned in time
  3. voice_prototype  - similarity to user-confirmed voice samples
  4. audio_cluster    - clustering only: distinguishes voices, does NOT name a person
Unresolved voices stay as 'Unknown Speaker [to be checked]'.
"""
from __future__ import annotations

from collections import defaultdict

from .store import PEOPLE, UNKNOWN

NATIVE_MIN_SHARE = 0.60
NATIVE_MIN_SECONDS = 20.0


def person_from_display_name(name: str) -> str | None:
    """Map a Meet display name to a known player. Matching is on display names only,
    never on what people say in the conversation."""
    n = (name or "").casefold()
    if not n:
        return None
    for person, info in PEOPLE.items():
        for alias in info["names"] + [person.casefold()]:
            if alias and alias in n.replace("i̇", "i"):
                return person
    return None


def label_for(person: str | None, cluster: str | None = None) -> str:
    if person in PEOPLE:
        return PEOPLE[person]["label"]
    return UNKNOWN


def native_cluster_evidence(entries: list[dict], turns: list[dict], participants: dict[str, dict]) -> dict:
    """entries: [{participant, start, end}] in recording seconds.
    turns: diarization turns. participants: participant resource name -> normalised dict.
    Returns {cluster: {participant, display, person, share, seconds}} for clusters with sufficient agreement."""
    by_cluster: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for e in entries:
        for t in turns:
            if t["start"] >= e["end"]:
                continue
            o = min(e["end"], t["end"]) - max(e["start"], t["start"])
            if o > 0:
                by_cluster[t["cluster"]][e["participant"]] += o
    res = {}
    for c, pm in by_cluster.items():
        total = sum(pm.values())
        if total <= 0:
            continue
        pid, sec = max(pm.items(), key=lambda kv: kv[1])
        share = sec / total
        if share >= NATIVE_MIN_SHARE and sec >= NATIVE_MIN_SECONDS:
            disp = participants.get(pid, {}).get("display", "")
            res[c] = {"participant": pid, "display": disp, "person": person_from_display_name(disp),
                      "share": round(share, 3), "seconds": round(sec, 1)}
    return res


def decide_clusters(clusters: list[str], native: dict, user: dict, proto: dict) -> dict:
    """Return per-cluster decision with provenance. Pure function."""
    out = {}
    for c in clusters:
        ev = []
        conflict = False
        person, conf, confirmed = None, 0.0, False
        n = native.get(c)
        u = user.get(c)
        p = proto.get(c)
        if n:
            ev.append({"source": "native_meet", "person": n.get("person"), "display": n.get("display"),
                       "share": n["share"]})
        if u:
            ev.append({"source": "user_confirmed", "person": u})
        if p:
            ev.append({"source": "voice_prototype", "person": p["person"], "score": p["score"]})
        persons = {e["person"] for e in ev if e.get("person")}
        if len(persons) > 1:
            conflict = True
        if u:
            person, conf, confirmed = u, 1.0, True
        elif n and n.get("person"):
            person, conf = n["person"], min(0.95, n["share"])
            if p and p["person"] != person:
                conflict = True
        elif p:
            person, conf = p["person"], round(min(0.9, max(0.0, p["score"])), 3)
        if not ev:
            ev.append({"source": "audio_cluster", "person": None,
                       "note": "Distinct voice found by clustering; no identity evidence yet."})
        out[c] = {"person": person, "confidence": conf, "confirmed": confirmed, "conflict": conflict,
                  "evidence": ev}
    return out


def apply_to_segments(segments: list[dict], decisions: dict, seg_overrides: dict | None = None,
                      seg_proto: dict | None = None) -> None:
    """Fill speaker / label / confidence / evidence fields on segments in place."""
    seg_overrides = seg_overrides or {}
    seg_proto = seg_proto or {}
    for s in segments:
        c = s.get("cluster")
        d = decisions.get(c) if c is not None else None
        ov = seg_overrides.get(s["id"])
        s["conflict"] = False
        if ov:
            s.update(speaker=ov, label=label_for(ov), speaker_confidence=1.0, speaker_confirmed=True,
                     evidence=[{"source": "user_confirmed", "person": ov}])
            continue
        if not d or not d["person"]:
            s.update(speaker=None, label=UNKNOWN, speaker_confidence=0.0, speaker_confirmed=False,
                     evidence=(d["evidence"] if d else [{"source": "none"}]))
            continue
        person = d["person"]
        evid = list(d["evidence"])
        sp = seg_proto.get(s["id"])
        if sp and sp["person"] != person and sp["margin"] >= 0.12 and not d["confirmed"]:
            s.update(speaker=None, label=UNKNOWN, speaker_confidence=round(0.3, 2), speaker_confirmed=False,
                     conflict=True,
                     evidence=evid + [{"source": "voice_prototype_segment", "person": sp["person"],
                                       "score": sp["score"]}],
                     candidates=[person, sp["person"]])
            continue
        s.update(speaker=person, label=label_for(person), speaker_confidence=d["confidence"],
                 speaker_confirmed=d["confirmed"], conflict=d["conflict"], evidence=evid)


def evidence_summary(meet: dict, probe: dict | None, native_map: dict, user: dict, proto_used: bool) -> dict:
    """Honest report of which evidence sources were actually available/used."""
    return {
        "meet_participants": bool(meet.get("participants")),
        "meet_transcript_entries": bool(meet.get("transcript_entries")),
        "native_identity_used": bool(native_map),
        "separate_audio_tracks": bool(probe and probe.get("has_separate_audio_tracks")),
        "audio_clustering": True,
        "user_calibration": bool(user),
        "voice_prototypes": proto_used,
        "visual_crosscheck": False,
    }
