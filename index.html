"""Chunked multilingual ASR (Turkish primary, English code-switching) with overlap handling.

Model policy: Whisper large-v3 by default. If it cannot run on the available hardware the
job fails with an explanation, it does NOT silently fall back to a weaker model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

CHUNK_S = 600.0
OVERLAP_S = 24.0

PHANTOM_PHRASES = [
    "altyazı m.k", "altyazı", "izlediğiniz için teşekkürler", "thanks for watching",
    "thank you for watching", "abone olmayı unutmayın", "bir sonraki videoda görüşmek üzere",
    "www.", "subtitles by", "amara.org", "sesli betimleme",
]

TR_WORDS = set("ve bir bu şu ne de da mi mı mu mü ama çok için gibi var yok ben sen o biz siz ki "
               "evet hayır tamam şimdi sonra zaten yani işte hani falan bence bana sana ona "
               "neden nasıl nerede peki ya be lan abi oğlum".split())
EN_WORDS = set("the a an and is are was were to of in that it you i we they he she this on for with "
               "not but have has had do does did what when where why how so just like okay yeah "
               "wait actually well right".split())


@dataclass
class Hardware:
    device: str
    compute_type: str
    gpu_name: str = ""
    vram_gb: float = 0.0
    notes: str = ""


def detect_hardware() -> Hardware:
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            name, vram = "NVIDIA GPU", 0.0
            try:
                import torch
                p = torch.cuda.get_device_properties(0)
                name, vram = p.name, p.total_memory / 1e9
            except Exception:
                pass
            if vram and vram < 6:
                return Hardware("cuda", "int8_float16", name, vram,
                                "Low VRAM: large-v3 runs with int8 quantisation (slower, same model).")
            return Hardware("cuda", "float16", name, vram, "GPU acceleration active.")
    except Exception:
        pass
    return Hardware("cpu", "int8", "", 0.0,
                    "No CUDA GPU detected. large-v3 on CPU is accurate but slow: expect roughly "
                    "1.5-4x the recording length. Processing is resumable.")


def text_lang_guess(text: str) -> str:
    toks = re.findall(r"[a-zçğıöşüâîû']+", text.lower())
    if not toks:
        return "unknown"
    tr = sum(t in TR_WORDS for t in toks) + 2 * sum(any(c in t for c in "çğıöşü") for t in toks)
    en = sum(t in EN_WORDS for t in toks)
    if en > tr * 1.5 and en >= 2:
        return "en"
    if tr > en:
        return "tr"
    return "mixed" if en and tr else "tr"


# ---------------------------------------------------------------- pure helpers


def plan_chunks(total_s: float, chunk_s: float = CHUNK_S, overlap_s: float = OVERLAP_S) -> list[dict]:
    """Chunks overlap by overlap_s. Each chunk 'owns' the region between handoff midpoints,
    so a word spoken in an overlap is kept from exactly one chunk."""
    if total_s <= 0:
        return []
    step = chunk_s - overlap_s
    chunks = []
    i, start = 0, 0.0
    while True:
        end = min(start + chunk_s, total_s)
        chunks.append({"idx": i, "start": start, "end": end})
        if end >= total_s:
            break
        i += 1
        start += step
    for k, c in enumerate(chunks):
        c["own_start"] = c["start"] if k == 0 else c["start"] + overlap_s / 2
        c["own_end"] = c["end"] if k == len(chunks) - 1 else c["end"] - overlap_s / 2
    return chunks


def is_phantom(seg: dict) -> bool:
    t = seg["text"].strip().lower()
    if not t:
        return True
    hit = any(p in t for p in PHANTOM_PHRASES)
    if hit and (seg.get("no_speech_prob", 0) > 0.4 or len(t) < 60):
        return True
    if seg.get("no_speech_prob", 0) > 0.8 and seg.get("avg_logprob", 0) < -1.0:
        return True
    if seg.get("compression_ratio", 0) > 2.8:
        return True
    # pathological repetition ("evet evet evet evet evet ...")
    toks = t.split()
    if len(toks) >= 8 and len(set(toks)) <= 2:
        return True
    return False


def merge_chunks(chunk_results: list[tuple[dict, list[dict]]]) -> tuple[list[dict], list[dict]]:
    """Keep each segment from the chunk that owns its midpoint.

    Returns (segments, boundary_flags). Flags mark segments near a handoff so the
    recheck stage can verify there is no duplicated or missing audio.
    """
    kept: list[dict] = []
    flags: list[dict] = []
    for chunk, segs in chunk_results:
        for s in segs:
            mid = (s["start"] + s["end"]) / 2
            if chunk["own_start"] <= mid < chunk["own_end"] or (
                    chunk["idx"] == 0 and mid < chunk["own_end"]):
                kept.append(s)
    kept.sort(key=lambda s: (s["start"], s["end"]))
    # Drop exact-text near-duplicates across boundary (same text, heavily overlapping time)
    out: list[dict] = []
    for s in kept:
        if out:
            p = out[-1]
            ov = min(p["end"], s["end"]) - max(p["start"], s["start"])
            if ov > 0.6 * min(p["end"] - p["start"], s["end"] - s["start"]) and \
                    _norm_text(p["text"]) == _norm_text(s["text"]):
                flags.append({"kind": "duplicate_dropped", "t": s["start"], "text": s["text"]})
                continue
        out.append(s)
    # Gaps at handoffs
    for chunk, _ in chunk_results[:-1]:
        h = chunk["own_end"]
        near = [s for s in out if abs(s["start"] - h) < 4 or abs(s["end"] - h) < 4]
        for s in near:
            flags.append({"kind": "boundary", "t": s["start"], "text": s["text"]})
    return out, flags


def _norm_text(t: str) -> str:
    return re.sub(r"\W+", " ", t.lower()).strip()


# ------------------------------------------------------------- model execution


class Transcriber:
    def __init__(self, settings: dict, glossary, models_dir: Path, hw: Hardware | None = None):
        self.settings = settings
        self.glossary = glossary
        self.hw = hw or detect_hardware()
        self.model_name = settings.get("asr_model", "large-v3")
        if self.model_name != "large-v3" and not settings.get("allow_smaller_model"):
            raise RuntimeError(
                f"Configured model '{self.model_name}' is not large-v3 and 'allow_smaller_model' is off. "
                "Refusing to run a lower-accuracy model without explicit consent.")
        from faster_whisper import WhisperModel
        self.model = WhisperModel(self.model_name, device=self.hw.device,
                                  compute_type=self.hw.compute_type, download_root=str(models_dir))

    def _transcribe(self, audio, language, offset: float, prompt: str | None):
        segs, info = self.model.transcribe(
            audio, language=language, task="transcribe", beam_size=5, best_of=5,
            temperature=(0.0, 0.2, 0.4), condition_on_previous_text=False,
            initial_prompt=prompt, hotwords=self.glossary.hotwords() or None,
            word_timestamps=True, vad_filter=True,
            vad_parameters=dict(threshold=0.4, min_silence_duration_ms=350, speech_pad_ms=250,
                                min_speech_duration_ms=120),
            no_speech_threshold=0.6, compression_ratio_threshold=2.4, log_prob_threshold=-1.0)
        out = []
        for s in segs:
            words = [{"w": w.word, "s": w.start + offset, "e": w.end + offset, "p": w.probability}
                     for w in (s.words or [])]
            out.append({"start": s.start + offset, "end": s.end + offset, "text": s.text.strip(),
                        "words": words, "avg_logprob": s.avg_logprob,
                        "no_speech_prob": s.no_speech_prob, "compression_ratio": s.compression_ratio,
                        "lang": language})
        return out

    def transcribe_chunk(self, wav: Path, chunk: dict) -> tuple[list[dict], list[dict]]:
        import soundfile as sf
        with sf.SoundFile(str(wav)) as f:
            sr = f.samplerate
            f.seek(int(chunk["start"] * sr))
            audio = f.read(int((chunk["end"] - chunk["start"]) * sr), dtype="float32")
        prompt = self.glossary.initial_prompt()
        segs = self._transcribe(audio, "tr", chunk["start"], prompt)
        suppressed = [s for s in segs if is_phantom(s)]
        segs = [s for s in segs if not is_phantom(s)]
        # Second opinion for English-looking or low-confidence segments
        for s in segs:
            guess = text_lang_guess(s["text"])
            if guess in ("en", "mixed") or s["avg_logprob"] < -0.9:
                a, b = int(max(0, s["start"] - 0.3 - chunk["start"]) * sr), int((s["end"] + 0.3 - chunk["start"]) * sr)
                clip = audio[a:b]
                if len(clip) < sr * 0.4:
                    continue
                alt = self._transcribe(clip, "en", s["start"] - 0.3 if s["start"] >= 0.3 else 0.0, None)
                alt = [x for x in alt if not is_phantom(x)]
                if not alt:
                    continue
                alt_text = " ".join(x["text"] for x in alt).strip()
                alt_lp = sum(x["avg_logprob"] for x in alt) / len(alt)
                if _norm_text(alt_text) != _norm_text(s["text"]):
                    s["alternatives"] = [{"text": alt_text, "lang": "en", "avg_logprob": alt_lp}]
                    if guess == "en" and alt_lp > s["avg_logprob"] + 0.15:
                        s["alternatives"].insert(0, {"text": s["text"], "lang": "tr",
                                                      "avg_logprob": s["avg_logprob"]})
                        s["text"], s["lang"] = alt_text, "en"
                        s["avg_logprob"] = alt_lp
                        s["words"] = [w for x in alt for w in x["words"]]
            s["lang_guess"] = text_lang_guess(s["text"])
        return segs, suppressed


def run_asr(job, settings: dict, glossary, models_dir: Path, progress: Callable[[float, str], None],
            should_stop: Callable[[], bool]) -> None:
    import soundfile as sf
    total = sf.info(str(job.audio_path)).duration
    chunks = plan_chunks(total)
    tr = Transcriber(settings, glossary, models_dir)
    job.add_evidence("asr_runtime", {"model": tr.model_name, "device": tr.hw.device,
                                     "compute_type": tr.hw.compute_type, "gpu": tr.hw.gpu_name,
                                     "note": tr.hw.notes})
    results, suppressed_all = [], []
    for c in chunks:
        if should_stop():
            raise InterruptedError("Stopped by user. Progress saved; resume to continue.")
        p = job.chunk_path("asr", c["idx"])
        if p.exists():  # resume
            d = job.read(f"asr/{c['idx']:04d}.json")
            results.append((c, d["segments"]))
            suppressed_all += d.get("suppressed", [])
            progress((c["idx"] + 1) / len(chunks), f"ASR chunk {c['idx'] + 1}/{len(chunks)} (cached)")
            continue
        segs, supp = tr.transcribe_chunk(job.audio_path, c)
        job.write(f"asr/{c['idx']:04d}.json", {"chunk": c, "segments": segs, "suppressed": supp})
        results.append((c, segs))
        suppressed_all += supp
        progress((c["idx"] + 1) / len(chunks), f"ASR chunk {c['idx'] + 1}/{len(chunks)}")
    merged, flags = merge_chunks(results)
    job.write("asr_merged.json", {"segments": merged, "boundary_flags": flags,
                                  "suppressed": suppressed_all, "duration": total})
