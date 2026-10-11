"""Local FastAPI server (127.0.0.1 only, per-launch token) serving the UI and JSON API."""
from __future__ import annotations

import secrets
import sys
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from . import exports, google_api as g, pipeline as pl
from .asr import detect_hardware
from .config import app_dir, load_settings, save_settings
from .glossary import Entry, Glossary
from .store import Job, PEOPLE, STAGES, UNKNOWN
from . import review as review_mod
from .media import cut_clip

TOKEN = secrets.token_urlsafe(24)
runner = pl.Runner()
app = FastAPI(title="ASOFAB Transcriber", docs_url=None, redoc_url=None)


def static_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "asofab" / "static"
    return Path(__file__).parent / "static"


@app.middleware("http")
async def guard(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        tok = request.headers.get("x-asofab-token") or request.query_params.get("t")
        if tok != TOKEN:
            return JSONResponse({"detail": "bad token"}, status_code=403)
        host = (request.headers.get("host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return JSONResponse({"detail": "bad host"}, status_code=403)
    return await call_next(request)


@app.exception_handler(g.GoogleError)
async def google_error(_: Request, exc: g.GoogleError):
    return JSONResponse({"detail": str(exc), "code": exc.code}, status_code=400)


@app.get("/", response_class=HTMLResponse)
def index():
    html = (static_dir() / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("__TOKEN__", TOKEN))


def _job(job_id: str) -> Job:
    if not (app_dir() / "jobs" / job_id / "job.json").exists():
        raise HTTPException(404, "unknown job")
    return Job(job_id)


# --------------------------------------------------------------------- setup


@app.get("/api/status")
def status():
    hw = detect_hardware()
    s = load_settings()
    s["hf_token_set"] = bool(s.pop("hf_token", ""))
    return {"signed_in": g.is_signed_in(), "client_secret": g.have_client_secret(),
            "hardware": hw.__dict__, "settings": s, "people": {k: v["label"] for k, v in PEOPLE.items()},
            "stages": STAGES}


@app.post("/api/google/client-secret")
def client_secret(body: dict = Body(...)):
    g.install_client_secret(body["text"])
    return {"ok": True}


@app.post("/api/google/connect")
def connect():
    g.connect_interactive()
    return {"ok": True}


@app.post("/api/google/signout")
def signout():
    g.sign_out()
    return {"ok": True}


@app.post("/api/settings")
def settings(body: dict = Body(...)):
    s = load_settings()
    allowed = {"hf_token", "asr_model", "allow_smaller_model", "delete_temp_audio_after",
               "expected_speakers", "min_speakers", "max_speakers", "cloud_transcription_consent"}
    for k, v in body.items():
        if k in allowed and not (k == "hf_token" and v == ""):
            s[k] = v
    save_settings(s)
    return {"ok": True}


# --------------------------------------------------------------------- jobs


def _start(job_id: str, **kw) -> None:
    try:
        runner.start(job_id, **kw)
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@app.post("/api/analyze")
def analyze(body: dict = Body(...)):
    link = (body.get("link") or "").strip()
    if not link:
        raise HTTPException(400, "Enter a Meet or Drive link.")
    job = Job.create(link)
    runner.start(job.id)
    return {"job": job.id}


@app.get("/api/jobs")
def jobs():
    return Job.list_all()


@app.get("/api/jobs/{job_id}")
def job_info(job_id: str):
    j = _job(job_id)
    m = j.meta()
    return {"meta": m, "running": runner.running(job_id), "progress": runner.progress.get(job_id)}


@app.post("/api/jobs/{job_id}/stop")
def stop(job_id: str):
    runner.stop(job_id)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/resume")
def resume(job_id: str):
    _job(job_id)
    _start(job_id)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/retry/{stage}")
def retry(job_id: str, stage: str):
    _job(job_id)
    if stage not in STAGES:
        raise HTTPException(400, "unknown stage")
    _start(job_id, only=stage, force=True)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/choose-record")
def choose_record(job_id: str, body: dict = Body(...)):
    j = _job(job_id)
    if runner.running(job_id):
        raise HTTPException(409, "This job is still running. Stop it first.")
    j.update_meta(choose_record=body.get("record"), recording_index=body.get("recording_index", 0))
    for s in STAGES:
        j.set_stage(s, "pending")
    _start(job_id)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/cleanup")
def cleanup(job_id: str):
    pl.delete_temp_files(_job(job_id))
    return {"ok": True}


# ----------------------------------------------------- transcript + speakers


@app.get("/api/jobs/{job_id}/segments")
def segments(job_id: str):
    return _job(job_id).segments()


@app.get("/api/jobs/{job_id}/review")
def review(job_id: str):
    return _job(job_id).review()


@app.get("/api/jobs/{job_id}/speakers")
def speakers(job_id: str):
    j = _job(job_id)
    spk = j.speakers()
    return {"speakers": spk, "samples": pl.calibration_samples(j) if j.segments() else {},
            "meet_participants": j.meta().get("meet", {}).get("participants", {})}


@app.post("/api/jobs/{job_id}/cluster")
def cluster(job_id: str, body: dict = Body(...)):
    pl.set_cluster_person(_job(job_id), body["cluster"], body.get("person"))
    return {"ok": True}


@app.post("/api/jobs/{job_id}/voice-sample")
def voice_sample(job_id: str, body: dict = Body(...)):
    pl.add_voice_sample(_job(job_id), body["person"], float(body["start"]), float(body["end"]))
    return {"ok": True}


@app.post("/api/jobs/{job_id}/prototypes")
def prototypes(job_id: str):
    try:
        return pl.recompute_prototypes(_job(job_id))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/jobs/{job_id}/segment/{seg_id}")
def edit_segment(job_id: str, seg_id: str, body: dict = Body(...)):
    j = _job(job_id)
    segs = j.segments()
    s = next((x for x in segs if x["id"] == seg_id), None)
    if not s:
        raise HTTPException(404)
    if "text" in body and body["text"] != s["text"]:
        s["text"], s["user_edited"] = body["text"], True
    if "ic_ooc" in body:
        s["ic_ooc"], s["ic_ooc_source"] = body["ic_ooc"], "user"
    if "speaker" in body:
        sp = body["speaker"]
        s["speaker"] = sp if sp in PEOPLE else None
        s["label"] = PEOPLE[sp]["label"] if sp in PEOPLE else UNKNOWN
        s["speaker_confirmed"], s["speaker_confidence"], s["conflict"] = sp in PEOPLE, 1.0 if sp in PEOPLE else 0.0, False
        s["evidence"] = [{"source": "user_confirmed", "person": sp}]
        spk = j.speakers()
        if sp in PEOPLE:
            spk.setdefault("segment_overrides", {})[seg_id] = sp
            spk.setdefault("samples", []).append({"person": sp, "start": s["start"], "end": s["end"]})
        else:
            spk.get("segment_overrides", {}).pop(seg_id, None)
        j.save_speakers(spk)
    j.save_segments(segs)
    return s


@app.post("/api/jobs/{job_id}/review/{rid}")
def resolve_review(job_id: str, rid: str, body: dict = Body(...)):
    try:
        return review_mod.resolve(_job(job_id), rid, body.get("text"), body.get("speaker"),
                                  body.get("status", "resolved"))
    except KeyError:
        raise HTTPException(404)


@app.get("/api/jobs/{job_id}/clip")
def clip(job_id: str, start: float, end: float, pad: float = 2.0):
    j = _job(job_id)
    if not j.audio_path.exists():
        raise HTTPException(404, "Temporary audio was deleted. Re-run the 'extract' stage to play audio.")
    d = j.dir / "clips"
    d.mkdir(exist_ok=True)
    a, b = max(0.0, start - pad), end + pad
    out = d / f"{a:.2f}_{b:.2f}.mp3"
    if not out.exists():
        cut_clip(j.audio_path, out, a, b)
    return FileResponse(out, media_type="audio/mpeg")


# ------------------------------------------------------------------- exports


@app.get("/api/jobs/{job_id}/export/{kind}")
def export(job_id: str, kind: str, ic: bool = False):
    j = _job(job_id)
    segs = j.segments()
    if kind == "md":
        body, name, mt = exports.full_transcript_md(segs, include_ic=ic), "ASOFAB_Full_Transcript.md", "text/markdown"
    elif kind == "csv":
        body, name, mt = exports.review_csv(j.review()), "ASOFAB_To_Be_Checked.csv", "text/csv"
    elif kind == "json":
        body, name, mt = exports.transcript_json(j.meta(), segs, j.review(), j.speakers()), \
            "ASOFAB_Transcript.json", "application/json"
    elif kind == "srt":
        body, name, mt = exports.srt(segs), "ASOFAB.srt", "application/x-subrip"
    elif kind == "chapter":
        body, name, mt = exports.chapter_source_md(segs), "ASOFAB_Chapter_Source.md", "text/markdown"
    else:
        raise HTTPException(404)
    return Response(body.encode("utf-8"), media_type=f"{mt}; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ------------------------------------------------------------------ glossary


@app.get("/api/glossary")
def glossary_get():
    from dataclasses import asdict
    return [asdict(e) for e in Glossary.load().entries]


@app.post("/api/glossary")
def glossary_put(body: dict = Body(...)):
    gl = Glossary.load()
    gl.upsert(Entry(canonical=body["canonical"], category=body.get("category", "term"),
                    aliases=body.get("aliases", []), ambiguous_aliases=body.get("ambiguous_aliases", []),
                    note=body.get("note", "")))
    gl.save()
    return {"ok": True}


@app.delete("/api/glossary/{canonical}")
def glossary_del(canonical: str):
    gl = Glossary.load()
    gl.remove(canonical)
    gl.save()
    return {"ok": True}
