"""Stage orchestration. Each stage persists its output; stages can be stopped, resumed and retried."""
from __future__ import annotations

import os
import re
import shutil
import threading
import traceback
from pathlib import Path
from typing import Callable

from . import google_api as g
from . import media, attribution, review as review_mod, annotate as annotate_mod
from .asr import run_asr
from .config import load_settings, models_dir
from .diarize import TurnIndex, assign_words, consolidate_clusters, run_diarization
from .glossary import Glossary
from .store import Job, STAGES, PEOPLE, UNKNOWN
from .urls import parse_link

MEET_NAME_RE = re.compile(r"([a-z]{3}-[a-z]{4}-[a-z]{3})", re.I)
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


class StopRequested(Exception):
    pass


# ------------------------------------------------------------------- resolve


def _allow_local() -> bool:
    return os.environ.get("ASOFAB_ALLOW_LOCAL") == "1"


def _collect_meet(record_name: str, rec_hint_file: str | None) -> dict:
    """Gather everything Meet exposes for one conference record. Each part may be missing or expired."""
    out: dict = {"record": record_name, "recordings": [], "participants": {}, "sessions": {},
                 "transcripts": [], "transcript_entries": [], "problems": []}

    def attempt(label, fn):
        try:
            return fn()
        except g.GoogleError as e:
            out["problems"].append(f"{label}: {e}")
            return None

    recs = attempt("recordings", lambda: g.list_recordings(record_name)) or []
    for r in recs:
        out["recordings"].append({
            "name": r.get("name"), "state": r.get("state"), "start": r.get("startTime"), "end": r.get("endTime"),
            "drive_file": (r.get("driveDestination") or {}).get("file", "").replace("files/", ""),
            "export_uri": (r.get("driveDestination") or {}).get("exportUri")})
    parts = attempt("participants", lambda: g.list_participants(record_name)) or []
    for p in parts:
        norm = g.participant_label(p)
        out["participants"][p["name"]] = norm
        ses = attempt("participant sessions", lambda p=p: g.list_participant_sessions(p["name"])) or []
        out["sessions"][p["name"]] = [{"start": s.get("startTime"), "end": s.get("endTime")} for s in ses]
    trs = attempt("transcripts", lambda: g.list_transcripts(record_name)) or []
    for t in trs:
        out["transcripts"].append({"name": t.get("name"), "state": t.get("state"),
                                   "doc": (t.get("docsDestination") or {}).get("document")})
        if t.get("state") in (None, "ENDED", "FILE_GENERATED", "STATE_UNSPECIFIED"):
            ents = attempt("transcript entries", lambda t=t: g.list_transcript_entries(t["name"])) or []
            for e in ents:
                out["transcript_entries"].append({
                    "participant": e.get("participant"), "text": e.get("text"), "lang": e.get("languageCode"),
                    "start": e.get("startTime"), "end": e.get("endTime")})
    if not out["transcripts"]:
        out["problems"].append("No Meet transcript exists for this meeting (transcription was probably off, "
                               "or Turkish is not supported by Meet's native transcription).")
    return out


def stage_resolve(job: Job, progress, stop) -> None:
    link = job.meta()["link"]
    if _allow_local() and Path(link).exists():
        job.update_meta(source_kind="local", local_path=link,
                        link_info={"kind": "local_file",
                                   "explanation": "Developer/test mode: local file. Not a Google source."})
        job.add_evidence("meet", {"available": False, "reason": "local test file"})
        return
    pl = parse_link(link)
    info = {"kind": pl.kind, "value": pl.value, "explanation": pl.explanation}
    if pl.kind == "unsupported":
        raise g.GoogleError(pl.explanation, "bad_link")
    progress(0.1, "Contacting Google")
    meet: dict = {}
    drive_id = None
    drive_meta = None
    candidates: list[dict] = []
    record = None

    if pl.kind == "meet_code":
        recs = g.list_conference_records(pl.value)
        if not recs:
            raise g.GoogleError(
                f"No conference records for {pl.value}. This is a meeting ROOM link; the meeting may be "
                "older than Meet's record retention, you may not be the organizer/participant, or the code is "
                "wrong. Paste the Drive recording link instead.", "no_records")
        candidates = [{"name": r["name"], "start": r.get("startTime"), "end": r.get("endTime"),
                       "duration_s": g.record_duration_s(r)} for r in recs]
        hint = job.meta().get("choose_record")
        record = next((r for r in recs if r["name"] == hint), None) or g.pick_best_record(recs)
        info["explanation"] += f" Found {len(recs)} historical instance(s); using {record['name']}."
    elif pl.kind == "conference_record":
        record = g.get_conference_record(pl.value)
    elif pl.kind == "drive_file":
        drive_id = pl.value
        drive_meta = g.drive_file_meta(drive_id)
        m = MEET_NAME_RE.search(drive_meta.get("name", ""))
        d = DATE_RE.search(drive_meta.get("name", ""))
        if m:
            try:
                recs = g.list_conference_records(m.group(1).lower())
                record = g.pick_best_record(recs, drive_meta, hint_date=d.group(1) if d else None)
            except g.GoogleError as e:
                meet["problems"] = [f"Could not associate recording with a conference record: {e}"]
        else:
            meet["problems"] = ["File name does not contain a Meet code; continuing with audio-based diarization."]

    if record:
        collected = _collect_meet(record["name"], drive_id)
        collected["record_start"], collected["record_end"] = record.get("startTime"), record.get("endTime")
        meet.update(collected)
        if pl.kind != "drive_file":
            files = [r["drive_file"] for r in collected["recordings"] if r["drive_file"]]
            if not files:
                raise g.GoogleError(
                    "This meeting has conference metadata but no accessible recording. Recording may not have "
                    "been enabled, may still be processing, or was deleted from Drive.", "no_recording")
            drive_id = files[min(job.meta().get("recording_index", 0), len(files) - 1)]
        elif drive_id not in [r["drive_file"] for r in collected["recordings"]]:
            meet.setdefault("problems", []).append(
                "The Drive file is not listed among this conference record's recordings; "
                "association with Meet metadata is unconfirmed.")
            meet["unconfirmed_association"] = True
    if not drive_id:
        raise g.GoogleError("Could not resolve a Drive recording file.", "no_recording")
    if drive_meta is None:
        drive_meta = g.drive_file_meta(drive_id)
    info.update(candidates=candidates, drive_file_id=drive_id, drive_name=drive_meta.get("name"),
                drive_size=drive_meta.get("size"),
                is_historical_recording=(pl.kind != "meet_code") or bool(record))
    job.update_meta(source_kind="drive", drive_file_id=drive_id, link_info=info, meet=meet)
    job.add_evidence("meet", {"available": bool(record), "participants": len(meet.get("participants", {})),
                              "transcript_entries": len(meet.get("transcript_entries", [])),
                              "problems": meet.get("problems", [])})


# -------------------------------------------------------- download / inspect / extract


def stage_download(job: Job, progress, stop) -> None:
    m = job.meta()
    if m.get("source_kind") == "local":
        return

    def prog(have, total):
        if stop():
            raise StopRequested()
        progress(have / total if total else 0.0, f"Downloading {have / 1e6:.0f} / {total / 1e6:.0f} MB")

    g.download_drive_file(m["drive_file_id"], job.source_path, prog)


def _source(job: Job) -> Path:
    m = job.meta()
    return Path(m["local_path"]) if m.get("source_kind") == "local" else job.source_path


def stage_inspect(job: Job, progress, stop) -> None:
    info = media.probe(_source(job))
    summ = media.summarize_probe(info)
    job.write("probe.json", {"raw_format": info.get("format"), "summary": summ})
    job.add_evidence("media", summ)


def stage_extract(job: Job, progress, stop) -> None:
    summ = job.read("probe.json")["summary"]
    idx = None
    if summ["has_separate_audio_tracks"]:
        idx = summ["audio_streams"][0]["index"]  # tracks used only when metadata proves they are per-participant
    progress(0.1, "Extracting audio")
    media.extract_audio(_source(job), job.audio_path, idx)


# --------------------------------------------------------------- asr / diarize


def stage_asr(job: Job, progress, stop) -> None:
    run_asr(job, load_settings(), Glossary.load(), models_dir(), progress, stop)


def stage_diarize(job: Job, progress, stop) -> None:
    run_diarization(job, load_settings(), progress)


# ----------------------------------------------------------------- attribution


def _meet_entries_in_recording_time(job: Job) -> list[dict]:
    meet = job.meta().get("meet", {})
    if not meet.get("transcript_entries"):
        return []
    rec = (meet.get("recordings") or [{}])[0]
    start = rec.get("start") or meet.get("record_start")
    if not start:
        return []
    t0 = g._parse_ts(start)
    out = []
    for e in meet["transcript_entries"]:
        if not (e.get("start") and e.get("end") and e.get("participant")):
            continue
        out.append({"participant": e["participant"],
                    "start": (g._parse_ts(e["start"]) - t0).total_seconds(),
                    "end": (g._parse_ts(e["end"]) - t0).total_seconds()})
    return out


def build_segments(job: Job) -> list[dict]:
    asr = job.read("asr_merged.json")
    dz = job.read("diarization.json")
    cmap = consolidate_clusters(dz["centroids"], dz["durations"], dz.get("expected_prior", 4))
    idx = TurnIndex(dz["turns"], cmap)
    boundary_t = [f["t"] for f in asr.get("boundary_flags", []) if f["kind"] == "boundary"]
    segs: list[dict] = []
    n = 0
    for s in asr["segments"]:
        for u in assign_words(s, idx):
            n += 1
            src = u.pop("src")
            u.update(id=f"S{n:05d}", cluster=u["cluster"], avg_logprob=src.get("avg_logprob"),
                     alternatives=src.get("alternatives", []), lang_guess=src.get("lang_guess"),
                     ic_ooc="Uncertain IC/OOC", ic_ooc_source="none",
                     boundary=any(u["start"] - 4 <= b <= u["end"] + 4 for b in boundary_t))
            u["text"] = u["text"].strip()
            if u["text"]:
                segs.append(u)
    job.write("cluster_map.json", cmap)
    return segs


def stage_attribute(job: Job, progress, stop) -> None:
    segs = build_segments(job)
    dz = job.read("diarization.json")
    turns = dz["turns"]
    cmap = job.read("cluster_map.json")
    merged_turns = [{**t, "cluster": cmap.get(t["cluster"], t["cluster"])} for t in turns]
    meet = job.meta().get("meet", {})
    native = attribution.native_cluster_evidence(
        _meet_entries_in_recording_time(job), merged_turns, meet.get("participants", {}))
    spk = job.speakers()
    spk["clusters"] = {c: {"seconds": round(sum(t["end"] - t["start"] for t in merged_turns if t["cluster"] == c), 1)}
                       for c in sorted({t["cluster"] for t in merged_turns})}
    spk["native"] = native
    job.save_speakers(spk)
    apply_attribution(job, segs)
    job.save_segments(segs)


def apply_attribution(job: Job, segs: list[dict]) -> None:
    spk = job.speakers()
    user = {c: p for c, p in spk.get("assignments", {}).items() if p}
    proto = spk.get("proto_clusters", {})
    decisions = attribution.decide_clusters(list(spk["clusters"]), spk.get("native", {}), user, proto)
    attribution.apply_to_segments(segs, decisions, spk.get("segment_overrides", {}), spk.get("segment_proto", {}))
    spk["decisions"] = decisions
    job.save_speakers(spk)
    probe = (job.read("probe.json") or {}).get("summary")
    job.add_evidence("attribution", attribution.evidence_summary(
        job.meta().get("meet", {}), probe, spk.get("native", {}), user, bool(proto)))


def stage_vocab(job: Job, progress, stop) -> None:
    gl = Glossary.load()
    segs = job.segments()
    for s in segs:
        if s.get("user_edited"):
            continue
        s["text_asr"] = s["text"]
        s["text"], flags = gl.correct(s["text"])
        s["glossary_flags"] = flags
        s["spelling_variants"] = gl.spelling_variants(s["text"])
    job.save_segments(segs)


def stage_recheck(job: Job, progress, stop) -> None:
    segs = job.segments()
    # chunk-boundary sanity: identical consecutive texts from the same speaker within 2s
    for a, b in zip(segs, segs[1:]):
        if a["text"].strip().lower() == b["text"].strip().lower() and abs(b["start"] - a["end"]) < 2.0 \
                and a.get("cluster") == b.get("cluster"):
            b["boundary"] = True
    job.save_segments(segs)


def stage_draft(job: Job, progress, stop) -> None:
    segs = job.segments()
    asr = job.read("asr_merged.json")
    dz = job.read("diarization.json")
    cmap = job.read("cluster_map.json") or {}
    turns = [{**t, "cluster": cmap.get(t["cluster"], t["cluster"])} for t in dz["turns"]]
    annotate_mod.annotate(segs)
    omissions = review_mod.find_omissions(turns, segs)
    old = {(r["seg_id"], r["start"]): r for r in job.review()}
    items = review_mod.build_review(segs, omissions)
    seen = set()
    for it in items:  # keep user work across re-drafts
        key = (it["seg_id"], it["start"])
        o = old.get(key)
        if o and o["status"] != "open":
            seen.add(key)
            it.update(status=o["status"], corrected_text=o["corrected_text"], corrected_speaker=o["corrected_speaker"])
            s = next((x for x in segs if x["id"] == it["seg_id"]), None)
            if s:
                s["review_open"] = False
    # A resolved item can stop being flagged once it is fixed (speaker confirmed, text edited).
    # It must stay in the checklist: the correction is the user's work and belongs in the CSV.
    for key, o in old.items():
        if o["status"] != "open" and key not in seen:
            items.append(o)
    items.sort(key=lambda r: r["start"])
    for n, it in enumerate(items, 1):
        it["id"] = f"R{n:04d}"
    job.save_segments(segs)
    job.save_review(items)
    job.add_evidence("suppressed_hallucinations", len(asr.get("suppressed", [])))


STAGE_FUNCS: dict[str, Callable] = {
    "resolve": stage_resolve, "download": stage_download, "inspect": stage_inspect, "extract": stage_extract,
    "asr": stage_asr, "diarize": stage_diarize, "attribute": stage_attribute, "vocab": stage_vocab,
    "recheck": stage_recheck, "draft": stage_draft,
}


# ----------------------------------------------------------------------- runner


class Runner:
    """Runs a job's pending stages on a background thread. Safe to stop and resume."""

    def __init__(self):
        self.threads: dict[str, threading.Thread] = {}
        self.stops: dict[str, threading.Event] = {}
        self.progress: dict[str, dict] = {}

    def running(self, job_id: str) -> bool:
        t = self.threads.get(job_id)
        return bool(t and t.is_alive())

    def stop(self, job_id: str) -> None:
        if job_id in self.stops:
            self.stops[job_id].set()

    def start(self, job_id: str, only: str | None = None, force: bool = False) -> None:
        if self.running(job_id):
            raise RuntimeError("This job is already running.")
        ev = threading.Event()
        self.stops[job_id] = ev
        t = threading.Thread(target=self._run, args=(job_id, only, force, ev), daemon=True)
        self.threads[job_id] = t
        t.start()

    def _run(self, job_id: str, only: str | None, force: bool, ev: threading.Event) -> None:
        job = Job(job_id)
        stages = [only] if only else STAGES
        try:
            for st in stages:
                if not force and job.stage_status(st) == "done":
                    continue
                if only:  # retrying one stage invalidates downstream stages
                    for later in STAGES[STAGES.index(st) + 1:]:
                        job.set_stage(later, "pending")
                job.set_stage(st, "running", error=None)

                def progress(frac, msg, st=st):
                    self.progress[job_id] = {"stage": st, "fraction": round(frac, 3), "message": msg}
                    job.set_stage(st, "running", fraction=round(frac, 3), message=msg)

                try:
                    STAGE_FUNCS[st](job, progress, ev.is_set)
                    job.set_stage(st, "done", fraction=1.0)
                except (InterruptedError, StopRequested):
                    job.set_stage(st, "stopped", message="Stopped. Resume to continue from saved progress.")
                    return
                except Exception as e:
                    code = getattr(e, "code", "error")
                    job.set_stage(st, "failed", error=str(e), code=code,
                                  trace=traceback.format_exc()[-1500:] if code == "error" else "")
                    return
        finally:
            if load_settings().get("delete_temp_audio_after") and all(
                    job.stage_status(s) == "done" for s in STAGES):
                delete_temp_files(job)


def delete_temp_files(job: Job) -> None:
    for p in (job.audio_path, job.source_path, job.source_path.with_suffix(".part")):
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass
    shutil.rmtree(job.dir / "clips", ignore_errors=True)


# --------------------------------------------------------------- calibration


def calibration_samples(job: Job, per_cluster: int = 5) -> dict:
    """Clear, non-overlapping utterances of 3-12 s per voice cluster for the calibration screen."""
    segs = job.segments()
    by: dict[str, list[dict]] = {}
    for s in segs:
        d = s["end"] - s["start"]
        if s.get("overlap") or not (3.0 <= d <= 12.0) or s.get("cluster") is None:
            continue
        by.setdefault(s["cluster"], []).append(s)
    out = {}
    for c, lst in by.items():
        lst.sort(key=lambda s: s.get("avg_logprob") or -9, reverse=True)
        picked: list[dict] = []
        for s in lst:  # spread over the recording
            if all(abs(s["start"] - p["start"]) > 120 for p in picked):
                picked.append(s)
            if len(picked) >= per_cluster:
                break
        out[c] = [{"seg_id": s["id"], "start": s["start"], "end": s["end"], "text": s["text"]} for s in picked]
    return out


def set_cluster_person(job: Job, cluster: str, person: str | None) -> None:
    spk = job.speakers()
    if person in (None, "", UNKNOWN):
        spk.get("assignments", {}).pop(cluster, None)
    else:
        if person not in PEOPLE:
            raise ValueError(f"Unknown person: {person}")
        spk.setdefault("assignments", {})[cluster] = person
    job.save_speakers(spk)
    segs = job.segments()
    apply_attribution(job, segs)
    job.save_segments(segs)
    stage_draft(job, lambda *a: None, lambda: False)


def add_voice_sample(job: Job, person: str, start: float, end: float) -> None:
    spk = job.speakers()
    spk.setdefault("samples", []).append({"person": person, "start": start, "end": end})
    job.save_speakers(spk)


def recompute_prototypes(job: Job) -> dict:
    """Build prototypes from confirmed samples and propagate through the recording."""
    from .voice import Embedder, build_prototypes, score_against
    spk = job.speakers()
    samples = list(spk.get("samples", []))
    for c, p in spk.get("assignments", {}).items():  # confirmed cluster assignments contribute samples too
        for s in calibration_samples(job).get(c, []):
            samples.append({"person": p, "start": s["start"], "end": s["end"]})
    if len({s["person"] for s in samples}) < 2:
        raise ValueError("Confirm voice samples for at least two people first.")
    emb = Embedder(load_settings().get("hf_token"))
    wav = str(job.audio_path)
    protos = build_prototypes(samples, emb, wav)
    segs = job.segments()
    seg_proto: dict = {}
    clus_scores: dict[str, dict[str, list[float]]] = {}
    for s in segs:
        if s.get("overlap") or s["end"] - s["start"] < 1.2:
            continue
        v = emb.embed(wav, s["start"], s["end"])
        person, score, margin = score_against(protos, v)
        seg_proto[s["id"]] = {"person": person, "score": round(score, 3), "margin": round(margin, 3)}
        clus_scores.setdefault(s["cluster"], {}).setdefault(person, []).append(score)
    proto_clusters = {}
    for c, d in clus_scores.items():
        person, vals = max(d.items(), key=lambda kv: sum(kv[1]))
        proto_clusters[c] = {"person": person, "score": round(sum(vals) / len(vals), 3)}
    spk["proto_clusters"], spk["segment_proto"] = proto_clusters, seg_proto
    job.save_speakers(spk)
    apply_attribution(job, segs)
    job.save_segments(segs)
    stage_draft(job, lambda *a: None, lambda: False)
    return proto_clusters
