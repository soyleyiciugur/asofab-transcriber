"""Stage orchestration, persistence, review corrections and the local HTTP API."""
import json
import time

import pytest

from asofab import pipeline as pl
from asofab import review as review_mod
from asofab.store import STAGES, UNKNOWN, Job


def _wait(runner, job_id, timeout=10):
    t0 = time.time()
    while runner.running(job_id) and time.time() - t0 < timeout:
        time.sleep(0.02)
    assert not runner.running(job_id)


def _seed_asr_and_diarization(job):
    """Simulated model outputs (no Whisper/pyannote available in tests)."""
    def w(word, s, e, p=0.9):
        return {"w": word, "s": s, "e": e, "p": p}
    segs = [
        {"start": 1, "end": 4, "text": "Gece ilerliyor hırrım",
         "words": [w(" Gece", 1, 2), w(" ilerliyor", 2, 3), w(" hırrım", 3, 4)], "avg_logprob": -0.2, "lang": "tr"},
        {"start": 5, "end": 8, "text": "Peki Visenor nerede",
         "words": [w(" Peki", 5, 6), w(" Visenor", 6, 7), w(" nerede", 7, 8)], "avg_logprob": -0.3, "lang": "tr"},
        {"start": 700, "end": 704, "text": "Ben hâlâ dışarıdayım",
         "words": [w(" Ben", 700, 701), w(" hâlâ", 701, 702), w(" dışarıdayım", 702, 704)], "avg_logprob": -0.25,
         "lang": "tr"},
    ]
    job.write("asr_merged.json", {"segments": segs, "boundary_flags": [], "suppressed": [{"text": "altyazı"}],
                                  "duration": 800})
    turns = [{"start": 0.5, "end": 4.5, "cluster": "SPEAKER_00"}, {"start": 4.8, "end": 8.5, "cluster": "SPEAKER_01"},
             {"start": 12, "end": 20, "cluster": "SPEAKER_00"},  # speech with no ASR text: omission
             {"start": 699, "end": 705, "cluster": "SPEAKER_01"}]
    job.write("diarization.json", {"turns": turns, "durations": {"SPEAKER_00": 12, "SPEAKER_01": 9.5},
                                   "centroids": {"SPEAKER_00": [1, 0], "SPEAKER_01": [0, 1]},
                                   "num_clusters": 2, "expected_prior": 4})


def _run_text_stages(job):
    for st in ("attribute", "vocab", "recheck", "draft"):
        pl.STAGE_FUNCS[st](job, lambda *a: None, lambda: False)


# ----------------------------------------------------------- job state

def test_job_state_is_persisted_atomically():
    j = Job.create("https://meet.google.com/abc-defg-hij")
    j.set_stage("resolve", "done")
    again = Job(j.id)
    assert again.stage_status("resolve") == "done" and again.stage_status("asr") == "pending"
    assert [x["id"] for x in Job.list_all()] == [j.id]


# ------------------------------------------------------------- runner

def test_runner_resumes_from_failed_stage(monkeypatch):
    calls = []
    fail = {"on": True}

    def make(name):
        def f(job, progress, stop):
            calls.append(name)
            if name == "asr" and fail["on"]:
                raise RuntimeError("boom")
        return f
    monkeypatch.setattr(pl, "STAGE_FUNCS", {s: make(s) for s in STAGES})
    j = Job.create("x")
    r = pl.Runner()
    r.start(j.id)
    _wait(r, j.id)
    assert j.stage_status("asr") == "failed" and "boom" in j.meta()["stages"]["asr"]["error"]
    assert j.stage_status("extract") == "done" and j.stage_status("diarize") == "pending"
    calls.clear()
    fail["on"] = False
    r.start(j.id)
    _wait(r, j.id)
    assert calls[0] == "asr" and "resolve" not in calls  # finished stages are not redone
    assert all(j.stage_status(s) == "done" for s in STAGES)


def test_retry_one_stage_invalidates_downstream(monkeypatch):
    monkeypatch.setattr(pl, "STAGE_FUNCS", {s: (lambda job, p, st: None) for s in STAGES})
    j = Job.create("x")
    r = pl.Runner()
    r.start(j.id)
    _wait(r, j.id)
    r.start(j.id, only="asr", force=True)
    _wait(r, j.id)
    assert j.stage_status("asr") == "done"
    assert all(j.stage_status(s) == "pending" for s in STAGES[STAGES.index("asr") + 1:])
    assert j.stage_status("extract") == "done"


def test_stop_then_resume(monkeypatch):
    def slow(job, progress, stop):
        for _ in range(200):
            if stop():
                raise InterruptedError()
            time.sleep(0.01)
    funcs = {s: (lambda job, p, st: None) for s in STAGES}
    funcs["asr"] = slow
    monkeypatch.setattr(pl, "STAGE_FUNCS", funcs)
    j = Job.create("x")
    r = pl.Runner()
    r.start(j.id)
    time.sleep(0.1)
    r.stop(j.id)
    _wait(r, j.id)
    assert j.stage_status("asr") == "stopped"
    funcs["asr"] = lambda job, p, st: None
    r.start(j.id)
    _wait(r, j.id)
    assert j.stage_status("draft") == "done"


def test_a_running_job_cannot_be_started_twice(monkeypatch):
    monkeypatch.setattr(pl, "STAGE_FUNCS", {s: (lambda job, p, st: time.sleep(0.3)) for s in STAGES})
    j = Job.create("x")
    r = pl.Runner()
    r.start(j.id)
    with pytest.raises(RuntimeError):
        r.start(j.id)
    r.stop(j.id)
    r.threads[j.id].join(5)


# ---------------------------------------------- local file end to end

def test_local_recording_runs_resolve_to_extract(mixed_stereo_mp4, monkeypatch):
    monkeypatch.setenv("ASOFAB_ALLOW_LOCAL", "1")
    j = Job.create(str(mixed_stereo_mp4))
    for st in ("resolve", "download", "inspect", "extract"):
        pl.STAGE_FUNCS[st](j, lambda *a: None, lambda: False)
    assert j.audio_path.exists()
    assert j.meta()["link_info"]["kind"] == "local_file"
    assert j.meta()["evidence"]["media"]["has_separate_audio_tracks"] is False


def test_bad_link_gives_a_clear_error():
    from asofab import google_api as g
    j = Job.create("https://example.com/nothing")
    with pytest.raises(g.GoogleError) as e:
        pl.stage_resolve(j, lambda *a: None, lambda: False)
    assert e.value.code == "bad_link"


# ----------------------------------------- draft without native evidence

def test_without_meet_data_nobody_is_named_and_nothing_is_forced(home):
    j = Job.create("x")
    _seed_asr_and_diarization(j)
    _run_text_stages(j)
    segs = j.segments()
    assert segs and all(s["label"] == UNKNOWN and s["speaker"] is None for s in segs)
    ev = j.meta()["evidence"]["attribution"]
    assert ev["native_identity_used"] is False and ev["audio_clustering"] is True
    assert j.meta()["evidence"]["suppressed_hallucinations"] == 1
    assert any("suspected_omission" in r["kinds"] for r in j.review())  # the 12-20 s gap is flagged


def test_glossary_applied_conservatively_in_draft():
    j = Job.create("x")
    _seed_asr_and_diarization(j)
    _run_text_stages(j)
    first = j.segments()[0]
    assert "Hrrm" in first["text"] and "hırrım" in first["text_asr"]


def test_user_confirmed_cluster_propagates_across_the_whole_recording():
    j = Job.create("x")
    _seed_asr_and_diarization(j)
    _run_text_stages(j)
    pl.set_cluster_person(j, "SPEAKER_01", "Ulaç")
    by_cluster = {}
    for s in j.segments():
        by_cluster.setdefault(s["cluster"], set()).add(s["label"])
    assert by_cluster["SPEAKER_01"] == {"Visenor (Ulaç)"}  # segments at 6 s and 700 s share one identity
    assert by_cluster["SPEAKER_00"] == {UNKNOWN}
    assert all(s["speaker_confirmed"] for s in j.segments() if s["cluster"] == "SPEAKER_01")
    pl.set_cluster_person(j, "SPEAKER_01", None)  # clearing returns to unknown
    assert all(s["label"] == UNKNOWN for s in j.segments())
    with pytest.raises(ValueError):
        pl.set_cluster_person(j, "SPEAKER_01", "Nobody")


def test_calibration_samples_are_clear_utterances():
    j = Job.create("x")
    _seed_asr_and_diarization(j)
    _run_text_stages(j)
    s = pl.calibration_samples(j)
    assert s and all(3.0 <= x["end"] - x["start"] <= 12.0 for lst in s.values() for x in lst)


# --------------------------------------------- review and corrections

def test_review_resolution_propagates_to_transcript_and_survives_redraft():
    j = Job.create("x")
    _seed_asr_and_diarization(j)
    _run_text_stages(j)
    item = next(r for r in j.review() if r["seg_id"])
    seg_id = item["seg_id"]
    review_mod.resolve(j, item["id"], "Düzeltilmiş cümle", "Taylan")
    seg = next(s for s in j.segments() if s["id"] == seg_id)
    assert seg["text"] == "Düzeltilmiş cümle" and seg["label"] == "Gaelor (Taylan)" and seg["user_edited"]
    assert next(r for r in j.review() if r["id"] == item["id"])["status"] == "resolved"
    pl.stage_draft(j, lambda *a: None, lambda: False)  # redrafting must not discard the user's work
    again = next(r for r in j.review() if r["seg_id"] == seg_id and r["start"] == item["start"])
    assert again["status"] == "resolved" and again["corrected_text"] == "Düzeltilmiş cümle"
    ids = [r["id"] for r in j.review()]
    assert len(ids) == len(set(ids))  # carried-over items never collide with new ids


def test_omission_resolution_inserts_a_user_authored_segment():
    j = Job.create("x")
    _seed_asr_and_diarization(j)
    _run_text_stages(j)
    om = next(r for r in j.review() if r["seg_id"] is None)
    before = len(j.segments())
    review_mod.resolve(j, om["id"], "Ben de geliyorum", "Uğur")
    segs = j.segments()
    assert len(segs) == before + 1
    new = next(s for s in segs if s.get("user_edited") and s["text"] == "Ben de geliyorum")
    assert new["start"] == om["start"]
    with pytest.raises(KeyError):
        review_mod.resolve(j, "R9999", "x", None)


# ---------------------------------------------------------- HTTP API

@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from asofab import server
    return TestClient(server.app, base_url="http://127.0.0.1"), server.TOKEN


def test_api_requires_token_and_local_host(client):
    c, tok = client
    assert c.get("/api/status").status_code == 403
    assert c.get("/api/status", headers={"x-asofab-token": "wrong"}).status_code == 403
    assert c.get("/api/status", headers={"x-asofab-token": tok}).status_code == 200
    from fastapi.testclient import TestClient
    from asofab import server
    evil = TestClient(server.app, base_url="http://evil.example.com")
    assert evil.get("/api/status", headers={"x-asofab-token": tok}).status_code == 403


def test_index_is_served_with_the_launch_token(client):
    c, tok = client
    r = c.get("/")
    assert r.status_code == 200 and "ASOFAB TRANSCRIBER" in r.text
    assert tok in r.text and "__TOKEN__" not in r.text


def test_status_never_leaks_the_hf_token(client):
    c, tok = client
    h = {"x-asofab-token": tok}
    assert c.post("/api/settings", json={"hf_token": "hf_secret123", "delete_temp_audio_after": True}, headers=h).status_code == 200
    s = c.get("/api/status", headers=h).json()
    assert "hf_secret123" not in json.dumps(s) and s["settings"]["hf_token_set"] is True
    c.post("/api/settings", json={"hf_token": ""}, headers=h)  # blank keeps the stored token
    assert c.get("/api/status", headers=h).json()["settings"]["hf_token_set"] is True
    c.post("/api/settings", json={"evil_key": 1}, headers=h)
    from asofab.config import load_settings
    assert "evil_key" not in load_settings()


def test_large_v3_is_never_silently_replaced():
    from asofab.asr import Transcriber
    from asofab.glossary import Glossary
    from asofab.config import models_dir
    with pytest.raises(RuntimeError, match="large-v3"):
        Transcriber({"asr_model": "tiny"}, Glossary(), models_dir())


def test_export_endpoints_and_api_edits(client):
    c, tok = client
    h = {"x-asofab-token": tok}
    j = Job.create("x")
    _seed_asr_and_diarization(j)
    _run_text_stages(j)
    sid = j.segments()[0]["id"]
    r = c.post(f"/api/jobs/{j.id}/segment/{sid}", json={"text": "Elle düzeltildi", "speaker": "Hasan", "ic_ooc": "IC"}, headers=h)
    assert r.status_code == 200 and r.json()["label"] == "GM (Haso)"
    md = c.get(f"/api/jobs/{j.id}/export/md?ic=true", headers=h)
    assert "ASOFAB_Full_Transcript.md" in md.headers["content-disposition"]
    assert "**GM (Haso) [IC]:** Elle düzeltildi" in md.text  # still flagged until resolved in To Be Checked
    assert "[IC]" not in c.get(f"/api/jobs/{j.id}/export/md", headers=h).text  # IC/OOC tags are optional
    assert c.get(f"/api/jobs/{j.id}/export/csv", headers=h).content.startswith("﻿".encode())
    assert json.loads(c.get(f"/api/jobs/{j.id}/export/json", headers=h).text)["segments"]
    assert "-->" in c.get(f"/api/jobs/{j.id}/export/srt", headers=h).text
    assert "Chapter Source" in c.get(f"/api/jobs/{j.id}/export/chapter", headers=h).text
    assert c.get(f"/api/jobs/{j.id}/export/zip", headers=h).status_code == 404
    assert c.get("/api/jobs/nope/segments", headers=h).status_code == 404
    assert c.get(f"/api/jobs/{j.id}/clip?start=1&end=2", headers=h).status_code == 404  # no temp audio


def test_glossary_api_roundtrip(client):
    c, tok = client
    h = {"x-asofab-token": tok}
    assert c.post("/api/glossary", json={"canonical": "Nyxara", "category": "dragon", "aliases": ["niksara"]}, headers=h).status_code == 200
    assert any(e["canonical"] == "Nyxara" for e in c.get("/api/glossary", headers=h).json())
    assert c.delete("/api/glossary/Nyxara", headers=h).status_code == 200
    assert not any(e["canonical"] == "Nyxara" for e in c.get("/api/glossary", headers=h).json())


def test_missing_oauth_client_is_a_readable_error(client):
    c, tok = client
    r = c.post("/api/google/connect", json={}, headers={"x-asofab-token": tok})
    assert r.status_code == 400 and r.json()["code"] == "no_client_secret"
    r = c.post("/api/google/client-secret", json={"text": json.dumps({"web": {}})}, headers={"x-asofab-token": tok})
    assert r.status_code == 400 and r.json()["code"] == "bad_client_secret"
