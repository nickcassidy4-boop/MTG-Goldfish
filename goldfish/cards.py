"""Card details from Scryfall (https://scryfall.com/docs/api), cached on disk.

Cards are looked up by name, 75 at a time (Scryfall's /cards/collection). Without network
access, give the details yourself with --cards cards.json: `python -m goldfish template
deck.txt` writes the file to fill in.
"""
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

SCRYFALL = "https://api.scryfall.com/cards/collection"
USER_AGENT = "mtg-goldfish-sim/1.0"
CACHE = Path(__file__).resolve().parent.parent / ".card-cache.json"
BASICS = {
    "plains": "W", "island": "U", "swamp": "B", "mountain": "R", "forest": "G", "wastes": "C",
}


@dataclass
class Card:
    name: str
    mana_cost: str = ""
    cmc: float = 0
    type_line: str = ""
    oracle_text: str = ""
    power: str | None = None
    toughness: str | None = None
    colors: list = field(default_factory=list)
    color_identity: list = field(default_factory=list)
    produced_mana: list = field(default_factory=list)
    keywords: list = field(default_factory=list)
    legalities: dict = field(default_factory=dict)

    @property
    def types(self) -> str:
        return self.type_line.split(" // ")[0]

    def is_type(self, t: str) -> bool:
        return t.lower() in self.types.lower()

    @property
    def is_land(self) -> bool:
        return self.is_type("land")

    @property
    def is_basic(self) -> bool:
        return self.is_type("basic") or self.name.lower().removeprefix("snow-covered ") in BASICS

    @property
    def can_be_commander(self) -> bool:
        return (self.is_type("legendary") and self.is_type("creature")) or "can be your commander" in self.oracle_text.lower()

    def has_keyword(self, word: str) -> bool:
        return any(k.lower() == word.lower() for k in self.keywords)

    @classmethod
    def from_scryfall(cls, c: dict) -> "Card":
        faces = c.get("card_faces") or []
        front = faces[0] if faces else c
        return cls(
            name=c["name"],
            mana_cost=front.get("mana_cost") or c.get("mana_cost") or "",
            cmc=float(c.get("cmc") or 0),
            type_line=front.get("type_line") or c.get("type_line") or "",
            oracle_text=c.get("oracle_text") or "\n//\n".join(f.get("oracle_text", "") for f in faces),
            power=front.get("power", c.get("power")),
            toughness=front.get("toughness", c.get("toughness")),
            colors=c.get("colors") or front.get("colors") or [],
            color_identity=c.get("color_identity") or [],
            produced_mana=c.get("produced_mana") or [],
            keywords=c.get("keywords") or [],
            legalities=c.get("legalities") or {},
        )

    @classmethod
    def from_dict(cls, d: dict) -> "Card":
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        known.setdefault("name", d.get("name", "?"))
        if "cmc" not in d and d.get("mana_cost"):
            known["cmc"] = mana_value(d["mana_cost"])
        return cls(**known)


def mana_value(cost: str) -> float:
    import re
    total = 0.0
    for sym in re.findall(r"\{([^}]+)\}", cost.split(" // ")[0]):
        if sym.isdigit():
            total += int(sym)
        elif sym in ("X", "Y", "Z"):
            continue
        elif sym.startswith("H"):
            total += 0.5
        else:
            total += 1
    return total


def key(name: str) -> str:
    return name.split(" // ")[0].strip().lower()


def _load_cache() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    try:
        CACHE.write_text(json.dumps(cache), encoding="utf-8")
    except OSError:
        pass  # read-only checkout: just don't cache


def _post(names: list) -> dict:
    body = json.dumps({"identifiers": [{"name": n} for n in names]}).encode()
    req = urllib.request.Request(SCRYFALL, data=body, headers={
        "User-Agent": USER_AGENT, "Accept": "application/json", "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.load(res)


def lookup(names: list, cards_file: str | None = None) -> tuple[dict, list, str | None]:
    """Card details for these names: ({name key: Card}, [names not found], error or None).
    cards_file: a JSON list of card details to use instead of (or before) Scryfall."""
    found: dict = {}
    wanted = list(dict.fromkeys(names))
    if cards_file:
        for d in json.loads(Path(cards_file).read_text(encoding="utf-8")):
            card = Card.from_dict(d)
            found[key(card.name)] = card
    cache = _load_cache()
    for n in wanted:
        if key(n) not in found and key(n) in cache:
            found[key(n)] = Card.from_dict(cache[key(n)])
    missing = [n for n in wanted if key(n) not in found]
    error = None
    for i in range(0, len(missing), 75):
        chunk = missing[i:i + 75]
        try:
            data = _post(chunk)
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            error = f"Couldn't reach Scryfall ({err}). Give the card details with --cards (see `python -m goldfish template`)."
            break
        for c in data.get("data", []):
            card = Card.from_scryfall(c)
            found[key(card.name)] = card
            cache[key(card.name)] = card.__dict__
            # Asked for by the front face only ("Fable of the Mirror-Breaker"): keep that key too.
            for n in chunk:
                if key(n) == key(card.name.split(" // ")[0]):
                    found[key(n)] = card
        time.sleep(0.1)  # Scryfall asks for 50-100 ms between requests
    # Split and double-faced cards asked for by their full name ("Beck // Call") are found by
    # Scryfall under the front face's name.
    retry = [n for n in wanted if key(n) not in found and " // " in n]
    if retry and not error:
        try:
            for c in _post([n.split(" // ")[0] for n in retry]).get("data", []):
                card = Card.from_scryfall(c)
                for n in retry:
                    if key(n) == key(card.name):
                        found[key(n)] = card
                        cache[key(n)] = card.__dict__
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
    _save_cache(cache)
    not_found = [n for n in wanted if key(n) not in found]
    return found, not_found, error
