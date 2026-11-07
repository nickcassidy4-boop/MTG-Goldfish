"""Running the simulator from another program (e.g. Deck Builder's server), without files or
the command line. Card details are passed in, so nothing is fetched from Scryfall.

    from goldfish.api import simulate
    report = simulate(
        cards=[{"name": "Sol Ring", "qty": 1}, {"name": "Mountain", "qty": 37}, ...],
        details=[{"name": "Sol Ring", "mana_cost": "{1}", "type_line": "Artifact",
                  "oracle_text": "{T}: Add {C}{C}.", ...}, ...],
        format="commander", commander="Krenko, Mob Boss", games=1000, turns=10)

Returns the report dict (deck-builder-playtest/1, as goldfish-report.json). Raises ValueError
with a plain message for anything that can't be simulated.
"""
import random

from . import abilities, report as report_mod, rules
from .cards import Card, key
from .sim import Game


def simulate(*, cards: list, details: list, format: str, commander: str | None = None, games: int = rules.DEFAULT_GAMES,
             turns: int | None = None, seed: int | None = None, name: str = "Deck", deck_id: str | None = None,
             max_games: int = rules.HARD_MAX) -> dict:
    fmt = rules.get_format(format)
    if not fmt:
        raise ValueError(f"Unknown format: {format}.")
    if not 1 <= games <= max_games:
        raise ValueError(f"Choose between 1 and {max_games:,} games.")
    turns = turns or rules.default_turns(fmt)
    if not 1 <= turns <= rules.MAX_TURNS:
        raise ValueError(f"Choose between 1 and {rules.MAX_TURNS} turns.")
    found = {key(d["name"]): Card.from_dict(d) for d in details if d.get("name")}
    cmd_model = None
    if fmt.commander:
        if not commander or key(commander) not in found:
            raise ValueError("A Commander deck needs its commander (with its card details).")
        cmd_model = abilities.model(found[key(commander)])
    library, missing, used_commander = [], [], False
    for c in cards:
        card = found.get(key(c["name"]))
        if not card:
            missing.append(c["name"])
            continue
        qty = int(c.get("qty", 1))
        if cmd_model and not used_commander and key(c["name"]) == key(commander):
            qty -= 1
            used_commander = True
        library.extend([abilities.model(card)] * max(0, qty))
    if len(library) < 20:
        raise ValueError("The deck needs at least 20 cards (besides the commander) to simulate.")
    models = {c.card.name: c for c in library}
    if cmd_model:
        models[cmd_model.card.name] = cmd_model
    rng = random.Random(seed)
    results = [Game(fmt, library, cmd_model, rng, turns, keep_log=(i == 0)).play() for i in range(games)]
    rep = report_mod.build(
        results, deck_name=name, commander=commander if fmt.commander else None, fmt=fmt, turns=turns, seed=seed,
        not_modelled=sorted(n for n, m in models.items() if not m.understood), deck_id=deck_id,
        held_back=sorted(n for n, m in models.items() if m.interaction))
    if missing:
        rep["method"] += f" Left out (no card details): {', '.join(missing)}."
    return rep
