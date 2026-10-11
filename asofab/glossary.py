"""Editable ASOFAB glossary: preferred spellings, spoken aliases, conservative correction.

Two independent ideas:
  * canonical  - preferred written form ("Hrrm")
  * aliases    - how it may be heard/spelled by ASR ("hırrım", "hirrim")
Correction only replaces when an alias matches a whole word AND (for risky
aliases that are ordinary words) the alias is flagged `needs_review`, in which
case the text is kept and a review item is produced instead of an auto-edit.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .config import glossary_path


@dataclass
class Entry:
    canonical: str
    category: str = "term"
    aliases: list[str] = field(default_factory=list)
    # Aliases that are also ordinary words. These are never auto-replaced.
    ambiguous_aliases: list[str] = field(default_factory=list)
    note: str = ""


def _e(cat: str, names: str, **kw) -> list[Entry]:
    return [Entry(n.strip(), cat, **kw) for n in names.split(",") if n.strip()]


PLAYERS = "Uğur, Ulaş, Ulaç, Ubeka, Taylan, Tay, Haso, Hasan, Hrrm, Tay-guy, Tay-gay, Tay-man, Gaylord"
PRIMARY = ("Jace, Jayce, Jacaelon, Jacaerys, Visenor, Arthur Sand, Gaelor, Baelenys, Vahaemon, Vhaemys, "
           "Malaenar, Jaery, Naella, Maela, Saera, Lorenah, Naela, Vaenarr, Aegor, Alysanne")
OTHERS = ("Almar Larchmont, Renrose Tyrell, Lorent Tyrell, Berholt Caswell, Timos Hightower, Derrin Hightower, "
          "Tion Lannister, Weylar Rocke, Cordin Poole, Curtass Whent, Brannyn Vance, Saathos Maris, Edmyn Uller, "
          "Perric Bracken, Tansy Riverside, Clover Tully, Harrik Greyjoy, Maron Dayne, Lyarra Karstark, "
          "Nymor Martell, Meria Martell, Annara Celtigar, Daria Sand, Drack Harlaw, Zekar Alasyr, Mydan Gerren, "
          "Merryn Whitespring, Reyenald Reyne, Nymos, Denlon Wickfen, Mara, Aldren")
DRAGONS = ("Maelwing, Jhagar, Cloudgazer, Bayle, Jadefyre, Boneskin, Ashfyre, Palefyre, Sunfyre, Sheepstealer, "
           "Boneskin's Egg, Unknown White Dragon")
HOUSES = ("Targaryen, Velaryon, Stark, Baratheon, Lannister, Tyrell, Hightower, Dayne, Martell, Arryn, Tully, "
          "Greyjoy, Gardener, Karstark, Mooton, Harlaw, Celtigar, Corbray, Reyne, Caswell, Marbrand, Blackwood, "
          "Bracken, Vance, Morrigen, Mullendore, Whent, Strong")
PLACES = ("King's Landing, Storm's End, Dragonstone, Driftmark, Starfall, Oldtown, Highgarden, Sunspear, "
          "Stepstones, Harrenhal, The Eyrie, The Twins, Moat Cailin, Winterfell, Castle Black, Riverrun, "
          "Casterly Rock, Braavos, Valyria, The Dreadfort, White Harbor, Naath, Gulltown, Pyke, Ashford, "
          "Bitterbridge, Summerhall, Rook's Rest, Kingswood, Blackwater Bay, Duskendale, Pentos, Tyrosh, Myr, "
          "Lys, Volantis, Astapor, Yunkai, Meereen, Asshai, The Red Mountains, The Prince's Pass, "
          "The Dornish Marches, Stone Hedge, Raventree Hall")
TERMS = ("ASOFAB, A Song of Fire and Blood, The Great Game, Westeros, Essos, High Valyrian, Iron Throne, "
         "Small Council, Kingsguard, Night's Watch, Hand of the King, Lord Commander, Maester, Grand Maester, "
         "Ser, Great House, dragonrider, raven, Direct Raven, Chronicle, Ledger, Royal Timeline, Inner Court, "
         "card, deck, deckbuilding, Power, Influence, Military, Political, Command, Royal Favor, trait, "
         "ability, draw, buff, damage, healing, tier, cost")

# Words that are also common Turkish/English words. Never auto-replaced.
ORDINARY_WORDS = {"ser", "mara", "card", "deck", "power", "influence", "military", "political", "command",
                  "trait", "ability", "draw", "buff", "damage", "healing", "tier", "cost", "raven", "strong",
                  "myr", "lys", "tay", "mara", "ubeka", "hasan"}


def default_entries() -> list[Entry]:
    out: list[Entry] = []
    out += _e("player", PLAYERS)
    out += _e("character", PRIMARY)
    out += _e("character", OTHERS)
    out += _e("dragon", DRAGONS)
    out += _e("house", HOUSES)
    out += _e("place", PLACES)
    out += _e("term", TERMS)
    for e in out:
        if e.canonical.lower() in ORDINARY_WORDS:
            e.ambiguous_aliases.append(e.canonical.lower())
    # Pronunciation aliases independent from preferred spelling.
    seed = {
        "Hrrm": ["hırrım", "hirrim", "hırım", "hrrm"],
        "Haso": ["haso", "haşo"],
        "Jace": ["jays", "ceys", "ceyz", "jeys"],
        "Visenor": ["vizenor", "visenor", "vaysenor"],
        "Gaelor": ["geylor", "gaylor", "gaelor"],
        "Ulaç": ["ulaç"],
        "Ulaş": ["ulaş"],
        "Uğur": ["uğur", "ugur"],
        "Dragonstone": ["dragon stone"],
        "Storm's End": ["storms end", "storm end"],
        "King's Landing": ["kings landing", "king landing"],
        "Targaryen": ["targaryan", "targeryen"],
        "Velaryon": ["velarion", "velaryan"],
    }
    by = {e.canonical: e for e in out}
    for name, al in seed.items():
        if name in by:
            by[name].aliases = sorted(set(by[name].aliases + al))
    # Deliberate joke names are preserved as-is. Never normalised.
    for joke in ("Tay-guy", "Tay-gay", "Tay-man", "Gaylord", "Hrrm", "Ubeka"):
        if joke in by:
            by[joke].note = "Deliberate nickname/joke name. Preserve exactly."
    return out


class Glossary:
    def __init__(self, entries: list[Entry] | None = None):
        self.entries = entries if entries is not None else default_entries()

    # persistence
    @classmethod
    def load(cls, path: Path | None = None) -> "Glossary":
        p = path or glossary_path()
        if p.exists():
            raw = json.loads(p.read_text(encoding="utf-8"))
            return cls([Entry(**e) for e in raw])
        g = cls()
        g.save(p)
        return g

    def save(self, path: Path | None = None) -> None:
        (path or glossary_path()).write_text(
            json.dumps([asdict(e) for e in self.entries], ensure_ascii=False, indent=1), encoding="utf-8")

    def upsert(self, e: Entry) -> None:
        for i, x in enumerate(self.entries):
            if x.canonical == e.canonical:
                self.entries[i] = e
                return
        self.entries.append(e)

    def remove(self, canonical: str) -> None:
        self.entries = [e for e in self.entries if e.canonical != canonical]

    # ASR bias
    def initial_prompt(self, max_chars: int = 600) -> str:
        """Short context string for Whisper's initial prompt. Whisper only reads the tail
        of the prompt (~224 tokens), so keep it compact and put the highest-value names last."""
        pri = [e.canonical for e in self.entries if e.category in ("player", "character", "dragon")
               and e.canonical.lower() not in ORDINARY_WORDS]
        places = [e.canonical for e in self.entries if e.category == "place"][:12]
        parts = places + pri
        s = "Tabletop oyunu: Hasan, Uğur, Ulaş, Taylan. " + ", ".join(parts)
        return s[-max_chars:]

    def hotwords(self, max_chars: int = 400) -> str:
        """Names handed to Whisper as hotwords. User-added entries come first so the length
        cap can never cut them off; the cap only trims whole words from the built-in list."""
        builtin = {e.canonical for e in default_entries()}
        names = [e.canonical for e in self.entries
                 if e.category in ("player", "character", "dragon")
                 and e.canonical.lower() not in ORDINARY_WORDS]
        names = [n for n in names if n not in builtin] + [n for n in names if n in builtin]
        out, used = [], 0
        for n in names:
            add = len(n) + (1 if out else 0)
            if used + add > max_chars:
                break
            out.append(n)
            used += add
        return " ".join(out)

    # conservative post-correction
    def _alias_map(self) -> dict[str, Entry]:
        m: dict[str, Entry] = {}
        for e in self.entries:
            for a in e.aliases:
                if a.lower() != e.canonical.lower():
                    m[_norm(a)] = e
        return m

    def correct(self, text: str) -> tuple[str, list[dict]]:
        """Replace recognised ASR variants with the preferred spelling.

        Returns (new_text, flags). A flag is produced instead of a replacement when
        the alias is an ordinary word or the match is only a near-spelling.
        Spoken alias for a deliberately altered joke name is never "fixed".
        """
        alias_map = self._alias_map()
        flags: list[dict] = []
        out = []
        pos = 0
        for m in re.finditer(r"[\wğüşöçıİĞÜŞÖÇ'’-]+", text):
            out.append(text[pos:m.start()])
            w = m.group(0)
            key = _norm(w)
            e = alias_map.get(key)
            if e is not None and w != e.canonical:
                if key in {_norm(a) for a in e.ambiguous_aliases} or w.lower() in ORDINARY_WORDS:
                    flags.append({"word": w, "suggest": e.canonical, "reason": "ambiguous_name",
                                  "start": m.start()})
                    out.append(w)
                else:
                    out.append(e.canonical)
            else:
                out.append(w)
            pos = m.end()
        out.append(text[pos:])
        return "".join(out), flags

    def spelling_variants(self, text: str) -> list[tuple[str, str]]:
        """Find words that are near-misses of known names (for 'inconsistent spelling' review)."""
        import difflib
        names = [e.canonical for e in self.entries if " " not in e.canonical and len(e.canonical) >= 5
                 and e.canonical.lower() not in ORDINARY_WORDS]
        low = {n.lower(): n for n in names}
        res = []
        for w in re.findall(r"[\wğüşöçıİ'’-]{5,}", text):
            lw = w.lower()
            if lw in low:
                if w != low[lw]:
                    res.append((w, low[lw]))
                continue
            close = difflib.get_close_matches(lw, list(low), n=1, cutoff=0.86)
            if close:
                res.append((w, low[close[0]]))
        return res


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s).replace("’", "'")
    return s.casefold().replace("i̇", "i")
