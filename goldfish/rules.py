"""Format rules the simulator follows: life, deck size, mulligans and the turn-1 draw.

Matches Deck Builder's formats (js/logic/formats.js). Goldfish games have one opponent
who does nothing; a game is won when the opponent's life reaches 0 (or, in Commander, when
one commander has dealt 21 combat damage).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Format:
    id: str
    name: str
    life: int
    deck_size: int          # exact for Commander, a minimum otherwise
    exact: bool
    commander: bool         # led by a commander (in the command zone)
    free_mulligan: bool     # the first mulligan costs nothing
    draw_first_turn: bool   # the player on the play draws on turn 1
    max_copies: int | None  # copies of a non-basic card (None: no limit)


FORMATS = {
    "commander": Format("commander", "Commander", 40, 100, True, True, True, True, 1),
    "standard": Format("standard", "Standard", 20, 60, False, False, False, False, 4),
    "pioneer": Format("pioneer", "Pioneer", 20, 60, False, False, False, False, 4),
    "modern": Format("modern", "Modern", 20, 60, False, False, False, False, 4),
    "legacy": Format("legacy", "Legacy", 20, 60, False, False, False, False, 4),
    "vintage": Format("vintage", "Vintage", 20, 60, False, False, False, False, 4),
    "pauper": Format("pauper", "Pauper", 20, 60, False, False, False, False, 4),
    "limited": Format("limited", "Limited (sealed or draft)", 20, 40, False, False, False, False, None),
}

ALIASES = {"edh": "commander", "cedh": "commander", "sealed": "limited", "draft": "limited"}

COMMANDER_DAMAGE = 21

# How many games make sense. Fewer than SENSIBLE_MIN gives numbers that swing a lot from run
# to run; more than SENSIBLE_MAX takes a long time for little extra accuracy.
SENSIBLE_MIN = 200
SENSIBLE_MAX = 20_000
HARD_MAX = 200_000
DEFAULT_GAMES = 1_000
DEFAULT_TURNS = {"commander": 10, "limited": 10}  # others: 8
MAX_TURNS = 30


def get_format(name: str | None) -> Format | None:
    if not name:
        return None
    key = name.strip().lower()
    return FORMATS.get(ALIASES.get(key, key))


def default_turns(fmt: Format) -> int:
    return DEFAULT_TURNS.get(fmt.id, 8)
