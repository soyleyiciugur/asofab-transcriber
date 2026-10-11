"""Voice prototypes from user-confirmed samples (speaker embeddings via pyannote/wespeaker)."""
from __future__ import annotations

import math
from collections import defaultdict


def _unit(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def mean_prototype(vectors: list[list[float]]) -> list[float]:
    d = len(vectors[0])
    m = [sum(v[i] for v in vectors) / len(vectors) for i in range(d)]
    return _unit(m)


def cos(a, b) -> float:
    return sum(x * y for x, y in zip(_unit(a), _unit(b)))


def score_against(prototypes: dict[str, list[float]], emb: list[float]) -> tuple[str, float, float]:
    """Return (best_person, best_score, margin_over_second)."""
    sc = sorted(((cos(p, emb), person) for person, p in prototypes.items()), reverse=True)
    best = sc[0]
    margin = best[0] - (sc[1][0] if len(sc) > 1 else 0.0)
    return best[1], best[0], margin


class Embedder:
    def __init__(self, hf_token: str | None):
        import torch
        from pyannote.audio import Model, Inference
        model = Model.from_pretrained("pyannote/wespeaker-voxceleb-resnet34-LM", use_auth_token=hf_token or None)
        self.inf = Inference(model, window="whole")
        if torch.cuda.is_available():
            self.inf.to(torch.device("cuda"))

    def embed(self, wav: str, start: float, end: float) -> list[float]:
        from pyannote.core import Segment
        v = self.inf.crop(wav, Segment(start, end))
        return [float(x) for x in v]


def build_prototypes(samples: list[dict], embedder: Embedder, wav: str) -> dict[str, list[float]]:
    by: dict[str, list] = defaultdict(list)
    for s in samples:
        if s.get("person"):
            by[s["person"]].append(embedder.embed(wav, s["start"], s["end"]))
    return {p: mean_prototype(v) for p, v in by.items() if v}
