"""Pure-logic tests: parsing, glossary, ASR planning, diarization helpers, attribution, review, exports."""
import re

from asofab import annotate, attribution, exports, media, review
from asofab import google_api as g
from asofab.asr import is_phantom, merge_chunks, plan_chunks, text_lang_guess
from asofab.diarize import TurnIndex, assign_words, consolidate_clusters
from asofab.glossary import Entry, Glossary
from asofab.store import UNKNOWN
from asofab.urls import parse_link


# ------------------------------------------------------------------ links

def test_meet_url_is_a_room_not_a_recording():
    p = parse_link("https://meet.google.com/abc-defg-hij?authuser=0")
    assert p.kind == "meet_code" and p.value == "abc-defg-hij"
    assert "ROOM" in p.explanation


def test_drive_file_url_is_a_specific_recording():
    p = parse_link("https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUv/view?usp=sharing")
    assert p.kind == "drive_file" and p.value == "1AbCdEfGhIjKlMnOpQrStUv"
    assert "specific recording" in p.explanation


def test_other_drive_url_shapes_and_ids():
    assert parse_link("https://drive.google.com/open?id=1AbCdEfGhIjKlMnOpQrStUv").kind == "drive_file"
    assert parse_link("1AbCdEfGhIjKlMnOpQrStUv").kind == "drive_file"
    assert parse_link("https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQrStUv").kind == "unsupported"


def test_conference_record_and_bad_inputs():
    p = parse_link("conferenceRecords/abc123XYZ")
    assert p.kind == "conference_record" and p.value == "abc123XYZ"
    assert parse_link("").kind == "unsupported"
    assert parse_link("https://example.com/x").kind == "unsupported"
    assert parse_link("https://meet.google.com/lookup/foo").kind == "unsupported"


# ----------------------------------------------------- conference records

def _rec(name, start, end):
    return {"name": name, "startTime": start, "endTime": end}


def test_pick_best_record_by_date_and_duration():
    recs = [_rec("conferenceRecords/a", "2026-09-01T18:00:00Z", "2026-09-01T19:00:00Z"),
            _rec("conferenceRecords/b", "2026-09-08T18:00:00Z", "2026-09-08T21:30:00Z")]
    assert g.pick_best_record(recs, hint_date="2026-09-01")["name"].endswith("/a")
    assert g.pick_best_record(recs, hint_duration_s=3.5 * 3600)["name"].endswith("/b")
    assert g.pick_best_record(recs)["name"].endswith("/b")  # no hint: most recent
    assert g.pick_best_record([]) is None


def test_pick_best_record_uses_drive_creation_time():
    recs = [_rec("conferenceRecords/a", "2026-09-01T18:00:00Z", "2026-09-01T19:00:00Z"),
            _rec("conferenceRecords/b", "2026-09-08T18:00:00Z", "2026-09-08T21:30:00Z")]
    best = g.pick_best_record(recs, drive_meta={"createdTime": "2026-09-01T19:05:00Z"})
    assert best["name"].endswith("/a")


# --------------------------------------------------------------- glossary

def test_alias_corrected_but_joke_names_preserved():
    gl = Glossary()
    out, flags = gl.correct("hırrım dedi ki Tay-guy geldi, jays de burada")
    assert "Hrrm" in out and "Jace" in out
    assert "Tay-guy" in out and flags == []


def test_names_that_are_ordinary_words_are_flagged_not_replaced():
    gl = Glossary([Entry("Raven Lord", "character", aliases=["raven"], ambiguous_aliases=["raven"])])
    out, flags = gl.correct("the raven flew away")
    assert out == "the raven flew away"
    assert flags and flags[0]["suggest"] == "Raven Lord"


def test_haso_stays_haso_and_ulac_ulas_not_conflated():
    gl = Glossary()
    assert gl.correct("Haso geldi")[0] == "Haso geldi"
    assert gl.correct("Ulaç ve Ulaş")[0] == "Ulaç ve Ulaş"


def test_custom_glossary_names_reach_the_asr_hints():
    gl = Glossary()
    gl.upsert(Entry("Zorgonaxel", "character"))
    assert "Zorgonaxel" in gl.hotwords()
    assert len(gl.hotwords()) <= 400
    assert "Zorgonaxel" in gl.initial_prompt()


def test_glossary_persists_and_edits(home):
    gl = Glossary.load()
    gl.upsert(Entry("Nyx", "dragon", aliases=["niks"]))
    gl.save()
    assert any(e.canonical == "Nyx" for e in Glossary.load().entries)
    gl2 = Glossary.load()
    gl2.remove("Nyx")
    gl2.save()
    assert not any(e.canonical == "Nyx" for e in Glossary.load().entries)


def test_spelling_variant_detection():
    gl = Glossary()
    assert ("Jacaeris", "Jacaerys") in gl.spelling_variants("Jacaeris geldi")


# -------------------------------------------------------------------- ASR

def test_chunk_plan_covers_everything_without_gaps():
    chunks = plan_chunks(3600 * 2 + 17)
    assert chunks[0]["own_start"] == 0 and chunks[-1]["own_end"] == chunks[-1]["end"]
    for a, b in zip(chunks, chunks[1:]):
        assert a["own_end"] == b["own_start"]  # every instant owned by exactly one chunk
        assert b["start"] < a["end"]  # real overlap for context
    assert plan_chunks(0) == []


def _seg(s, e, text, **kw):
    return {"start": s, "end": e, "text": text, **kw}


def test_each_word_kept_from_exactly_one_chunk_and_duplicates_dropped():
    c0, c1 = plan_chunks(1300)[:2]
    boundary = c0["own_end"]
    dup0 = _seg(boundary - 3, boundary - 1, "kılıcı al")  # owned by chunk 0
    dup1 = _seg(boundary - 3, boundary - 1, "kılıcı al")  # same speech heard by chunk 1: not owned
    other = _seg(boundary + 5, boundary + 7, "tamam")
    merged, flags = merge_chunks([(c0, [dup0]), (c1, [dup1, other])])
    assert [s["text"] for s in merged] == ["kılıcı al", "tamam"]


def test_phantom_phrases_on_silence_are_dropped_but_real_speech_survives():
    assert is_phantom(_seg(0, 2, "Altyazı M.K.", no_speech_prob=0.7))
    assert is_phantom(_seg(0, 2, "evet " * 10))
    assert is_phantom(_seg(0, 2, ""))
    assert not is_phantom(_seg(0, 2, "Bence ejderha Storm's End'e gitmeli", no_speech_prob=0.02, avg_logprob=-0.3))


def test_language_guess_handles_code_switching():
    assert text_lang_guess("Ben hâlâ dışarıdayım yani") == "tr"
    assert text_lang_guess("wait actually that is not what I said") == "en"
    assert text_lang_guess("ben bunu yapmayacağım but you can do it") in ("mixed", "tr")


# ----------------------------------------------------------- diarization

def test_minor_similar_cluster_merged_distinct_one_kept():
    cent = {"A": [1, 0, 0, 0], "B": [0, 1, 0, 0], "C": [0, 0, 1, 0], "D": [0, 0, 0, 1],
            "E": [0.99, 0.1, 0, 0], "F": [0.5, 0.5, 0.5, 0.5]}
    dur = {"A": 500, "B": 400, "C": 300, "D": 250, "E": 20, "F": 30}
    m = consolidate_clusters(cent, dur, expected=4)
    assert m["E"] == "A"  # tiny and very similar: merged
    assert m["F"] == "F"  # tiny but distinct: kept, never forced into a speaker
    assert all(m[k] == k for k in "ABCD")


def test_four_speaker_interruption_splits_utterances():
    turns = [{"start": 0, "end": 2, "cluster": "A"}, {"start": 2, "end": 3, "cluster": "B"},
             {"start": 3, "end": 5, "cluster": "A"}]
    words = [{"w": " Ben", "s": 0.0, "e": 0.5, "p": .9}, {"w": " gidiyorum", "s": 0.5, "e": 1.0, "p": .9},
             {"w": " ama", "s": 1.0, "e": 1.5, "p": .9}, {"w": " hayır", "s": 2.1, "e": 2.5, "p": .9},
             {"w": " bekle", "s": 3.1, "e": 3.5, "p": .9}, {"w": " dedim", "s": 3.5, "e": 4.0, "p": .9}]
    seg = {"start": 0, "end": 4, "text": "x", "words": words, "lang": "tr"}
    out = assign_words(seg, TurnIndex(turns))
    assert [u["cluster"] for u in out] == ["A", "B", "A"]
    assert out[1]["text"] == "hayır"


def test_simultaneous_speech_is_flagged_as_overlap():
    turns = [{"start": 0, "end": 3, "cluster": "A"}, {"start": 1, "end": 2, "cluster": "B"}]
    seg = {"start": 1, "end": 2, "text": "x", "lang": "tr",
           "words": [{"w": " şey", "s": 1.2, "e": 1.8, "p": .8}]}
    out = assign_words(seg, TurnIndex(turns))
    assert out[0]["overlap"] and out[0]["overlaps_with"]


def test_identity_stable_across_chunk_boundary():
    turns = [{"start": 0, "end": 1300, "cluster": "SPEAKER_01"}]
    idx = TurnIndex(turns)
    before = assign_words({"start": 590, "end": 592, "text": "a", "words": [], "lang": "tr"}, idx)[0]
    after = assign_words({"start": 612, "end": 614, "text": "b", "words": [], "lang": "tr"}, idx)[0]
    assert before["cluster"] == after["cluster"] == "SPEAKER_01"


# ------------------------------------------------------------ attribution

def test_display_names_map_to_players_never_conversation():
    f = attribution.person_from_display_name
    assert f("Haso") == "Hasan" and f("Ulaş K.") == "Ulaç" and f("uğur") == "Uğur"
    assert f("Taylan") == "Taylan" and f("Someone Else") is None and f("") is None


def test_native_evidence_needs_enough_agreement():
    parts = {"p1": {"display": "Uğur"}}
    turns = [{"start": 0, "end": 60, "cluster": "A"}]
    ok = attribution.native_cluster_evidence([{"participant": "p1", "start": 0, "end": 40}], turns, parts)
    assert ok["A"]["person"] == "Uğur"
    short = attribution.native_cluster_evidence([{"participant": "p1", "start": 0, "end": 5}], turns, parts)
    assert short == {}


def test_hierarchy_user_beats_native_and_conflict_is_recorded():
    native = {"A": {"person": "Uğur", "display": "Uğur", "share": 0.9}}
    d = attribution.decide_clusters(["A"], native, {"A": "Taylan"}, {})["A"]
    assert d["person"] == "Taylan" and d["confirmed"] and d["conflict"]
    d = attribution.decide_clusters(["A"], native, {}, {})["A"]
    assert d["person"] == "Uğur" and not d["confirmed"] and d["confidence"] <= 0.95


def test_clustering_alone_names_nobody():
    d = attribution.decide_clusters(["A"], {}, {}, {})["A"]
    assert d["person"] is None and d["evidence"][0]["source"] == "audio_cluster"
    segs = [{"id": "S1", "cluster": "A"}]
    attribution.apply_to_segments(segs, {"A": d})
    assert segs[0]["label"] == UNKNOWN and segs[0]["speaker"] is None


def test_unrecognised_display_name_does_not_invent_identity():
    native = {"A": {"person": None, "display": "Guest 7", "share": 1.0}}
    d = attribution.decide_clusters(["A"], native, {}, {})["A"]
    assert d["person"] is None


def test_segment_level_voice_disagreement_becomes_unknown_unless_confirmed():
    dec = attribution.decide_clusters(["A"], {"A": {"person": "Uğur", "display": "x", "share": 0.8}}, {}, {})
    seg_proto = {"S1": {"person": "Taylan", "score": 0.8, "margin": 0.2}}
    s = [{"id": "S1", "cluster": "A"}]
    attribution.apply_to_segments(s, dec, seg_proto=seg_proto)
    assert s[0]["label"] == UNKNOWN and s[0]["conflict"]
    dec = attribution.decide_clusters(["A"], {}, {"A": "Uğur"}, {})
    s = [{"id": "S1", "cluster": "A"}]
    attribution.apply_to_segments(s, dec, seg_proto=seg_proto)
    assert s[0]["speaker"] == "Uğur" and s[0]["speaker_confirmed"]


def test_evidence_summary_is_honest():
    e = attribution.evidence_summary({}, None, {}, {}, False)
    assert not e["meet_participants"] and not e["native_identity_used"]
    assert e["audio_clustering"] and not e["visual_crosscheck"]


# ---------------------------------------------------------------- review

def test_review_flags_each_kind():
    s = {"id": "S1", "text": "şey", "start": 1, "end": 2, "speaker": None, "cluster": "A",
         "words": [{"w": "şey", "s": 1, "e": 2, "p": 0.1}], "avg_logprob": None,
         "alternatives": [{"text": "they"}], "glossary_flags": [{"word": "raven", "suggest": "Raven Lord"}]}
    kinds = [k for k, _ in review.segment_kinds(s, None, None)]
    assert {"unintelligible", "speaker_uncertain", "competing_asr", "ambiguous_name"} <= set(kinds)


def test_omission_detection_and_review_items():
    turns = [{"start": 0, "end": 10, "cluster": "A"}]
    segs = [{"id": "S1", "start": 0, "end": 2, "text": "merhaba", "cluster": "A", "speaker": "Uğur",
             "label": "Jace (Uğur)", "words": [], "avg_logprob": -0.2}]
    om = review.find_omissions(turns, segs)
    assert om and om[0]["start"] == 2 and om[0]["end"] == 10
    items = review.build_review(segs, om)
    assert any(i["kinds"] == ["suspected_omission"] for i in items)
    assert items[-1]["previous"] == "merhaba"


# --------------------------------------------------------------- exports

SEGS = [
    {"id": "S1", "start": 1.0, "end": 3.0, "text": "Gece ilerliyor.", "label": "GM (Haso)", "ic_ooc": "GM Narration"},
    {"id": "S2", "start": 3.0, "end": 4.0, "text": "Hava soğuyor.", "label": "GM (Haso)", "ic_ooc": "GM Narration"},
    {"id": "S3", "start": 4.0, "end": 6.0, "text": "Wait, actually...", "label": "Visenor (Ulaç)", "ic_ooc": "IC"},
    {"id": "S4", "start": 6.0, "end": 7.0, "text": "bir şey", "label": UNKNOWN, "ic_ooc": "OOC", "review_open": True},
]


def test_markdown_has_no_timestamps_and_keeps_structure():
    md = exports.full_transcript_md(SEGS)
    assert not re.search(r"\d\d:\d\d", md)
    assert "**GM (Haso) [GM Narration]:** Gece ilerliyor. Hava soğuyor." in md
    assert "**Visenor (Ulaç) [IC]:** Wait, actually..." in md
    assert f"**{UNKNOWN} [OOC]:** bir şey [to be checked]" in md
    assert "[GM Narration]" not in exports.full_transcript_md(SEGS, include_ic=False)


def test_csv_has_bom_and_all_columns():
    item = {"id": "R0001", "speaker": UNKNOWN, "previous": "a", "uncertain": "b", "next": "c", "issue": "x",
            "alternatives": ["p", "q"], "start": 61.5, "end": 63, "status": "open", "corrected_text": ""}
    out = exports.review_csv([item])
    assert out.startswith("\ufeff") and "p | q" in out and "00:01:01.500" in out
    assert out.splitlines()[0].count(",") == 9


def test_srt_and_json_and_chapter_source():
    srt = exports.srt(SEGS)
    assert "00:00:01,000 --> 00:00:03,000" in srt and "GM (Haso): Gece ilerliyor." in srt
    import json
    data = json.loads(exports.transcript_json({"link": "x"}, SEGS, [], {}))
    assert len(data["segments"]) == 4 and data["segments"][3]["needs_review"] is True
    ch = exports.chapter_source_md(SEGS)
    assert "No chapter has been written" in ch and exports.ANCHOR in ch
    assert "Out-of-character" in ch


def test_ic_ooc_is_conservative():
    segs = [{"text": "bir dakika, kurala bakıyorum", "speaker": "Hasan"},
            {"text": "Peki Visenor nerede şu an", "speaker": "Uğur"},
            {"text": " ".join(["gece"] * 30), "speaker": "Hasan"}]
    annotate.annotate(segs)
    assert [s["ic_ooc"] for s in segs] == ["OOC", "Uncertain IC/OOC", "GM Narration"]
    segs[1]["ic_ooc"], segs[1]["ic_ooc_source"] = "IC", "user"
    annotate.annotate(segs)
    assert segs[1]["ic_ooc"] == "IC"  # user decisions are never overwritten


# ----------------------------------------------------------------- media

def test_mixed_stereo_is_not_treated_as_two_people(mixed_stereo_mp4):
    info = media.probe(mixed_stereo_mp4)
    summ = media.summarize_probe(info)
    assert len(summ["audio_streams"]) == 1 and summ["audio_streams"][0]["channels"] == 2
    assert summ["has_separate_audio_tracks"] is False
    assert any("NOT treated as separate people" in n for n in summ["notes"])


def test_audio_extraction_is_mono_16k(mixed_stereo_mp4, tmp_path):
    out = media.extract_audio(mixed_stereo_mp4, tmp_path / "a.wav")
    import soundfile as sf
    i = sf.info(str(out))
    assert i.channels == 1 and i.samplerate == 16000 and 5.5 < i.duration < 6.5


def test_multiple_streams_without_metadata_are_not_separate_tracks():
    info = {"streams": [{"codec_type": "audio", "index": 0, "channels": 1},
                        {"codec_type": "audio", "index": 1, "channels": 1}], "format": {}}
    assert media.summarize_probe(info)["has_separate_audio_tracks"] is False


def test_ffprobe_failure_message_is_never_empty(tmp_path):
    import pytest
    junk = tmp_path / "notmedia.bin"
    junk.write_bytes(b"this is not a recording")
    with pytest.raises(RuntimeError) as e:
        media.probe(junk)
    msg = str(e.value)
    assert msg.startswith("ffprobe failed (exit code") and not msg.rstrip().endswith(":")
