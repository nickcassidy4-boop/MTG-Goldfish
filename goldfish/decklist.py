"""Reading a pasted deck list: MTG Arena / MTGO exports, Moxfield, Archidekt, Deck Builder's
helper builds, or plain "4 Lightning Bolt" lines.

Sections are recognised by headings ("Commander", "Deck", "Main", "Sideboard", "Maybeboard",
"Companion"). Lines like "1 Sol Ring (C21) 263 *F* [Ramp]" keep just the count and name.
"""
import re
from dataclasses import dataclass, field

SECTIONS = {
    "commander": "commander", "commanders": "commander",
    "deck": "main", "main": "main", "mainboard": "main", "main deck": "main", "maindeck": "main",
    "sideboard": "side", "side": "side", "maybeboard": "maybe", "maybe": "maybe", "considering": "maybe",
    "companion": "companion", "tokens": "skip", "about": "skip",
}
LINE = re.compile(r"^\s*(?:SB:\s*)?(\d+)\s*[xX]?\s+(.+?)\s*$")
TRAILING = [
    re.compile(r"\s*\[[^\]]*\]\s*$"),             # [Ramp] categories
    re.compile(r"\s*\*[A-Z]+\*\s*$"),             # *F* foil marks
    re.compile(r"\s*\(([A-Za-z0-9]{2,6})\)\s*[\w-]*\s*$"),  # (C21) 263 set and number
    re.compile(r"\s*#\S+\s*$"),                   # #tags
    re.compile(r"\s+\^[^^]*\^\s*$"),              # ^Have^ Archidekt labels
]


@dataclass
class Entry:
    qty: int
    name: str
    section: str = "main"


@dataclass
class DeckList:
    entries: list = field(default_factory=list)
    commander_named: list = field(default_factory=list)  # from a "Commander" section
    notes: list = field(default_factory=list)            # lines that couldn't be read

    def section(self, name: str) -> list:
        return [e for e in self.entries if e.section == name]

    @property
    def main_count(self) -> int:
        return sum(e.qty for e in self.entries if e.section in ("main", "commander"))


def clean_name(text: str) -> str:
    name = text.strip()
    for _ in range(3):
        for pattern in TRAILING:
            name = pattern.sub("", name)
    return name.strip().strip('"')


def parse(text: str) -> DeckList:
    deck = DeckList()
    section = "main"
    for raw in text.replace("﻿", "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("//", "#")) and not line.lower().startswith("#commander"):
            continue
        heading = line.rstrip(":").strip().lower()
        heading = re.sub(r"\s*\(\d+\)$", "", heading)  # "Deck (99)"
        if heading in SECTIONS:
            section = SECTIONS[heading]
            continue
        m = LINE.match(line)
        if not m:
            deck.notes.append(line)
            continue
        if section == "skip":
            continue
        qty, name = int(m.group(1)), clean_name(m.group(2))
        if not name or qty <= 0:
            continue
        sec = "side" if raw.lstrip().upper().startswith("SB:") else section
        deck.entries.append(Entry(qty, name, sec))
        if sec == "commander":
            deck.commander_named.append(name)
    return deck
