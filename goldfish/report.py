"""Adds up the games into a report: JSON in Deck Builder's play-test format
(deck-builder-playtest/1, so it can be pasted into a deck's Play-test tab) and a Markdown
summary for reading in the chat.

The numbers are filled in here. The words (summary, strengths, weaknesses, suggestions) are
left for the AI to write from them: see CLAUDE.md.
"""
import statistics
from collections import Counter, defaultdict

FORMAT = "deck-builder-playtest/1"
TOOL = "mtg-goldfish-sim 1.0"


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def _rate(n, total):
    return round(n / total, 3) if total else None


def build(results: list, *, deck_name: str, commander: str | None, fmt, turns: int, seed, not_modelled: list,
          deck_id: str | None = None, held_back: list = ()) -> dict:
    games = len(results)
    kills = [r.kill_turn for r in results if r.kill_turn is not None]
    by_turn = Counter(kills)

    def per_turn(attr, carry=False):
        out = []
        for t in range(turns):
            vals = []
            for r in results:
                if t < len(r.turns):
                    vals.append(getattr(r.turns[t], attr))
                elif carry and r.turns:
                    vals.append(getattr(r.turns[-1], attr))  # the game was already won: it stays at its total
            out.append(_mean(vals) if vals else None)
        return out

    def lands_at(r, t):
        return r.turns[t - 1].lands if len(r.turns) >= t else r.turns[-1].lands if r.turns else 0

    on_curve = sum(1 for r in results if all(lands_at(r, t) >= t for t in range(1, 5)))
    screw = sum(1 for r in results if lands_at(r, 4) < 3)
    flood = sum(1 for r in results if len(r.turns) >= 7 and r.turns[6].lands >= 7 and r.turns[6].hand <= 1)

    # Key cards: how much sooner the deck wins when the card was cast by turn 4.
    win_turn = {id(r): (r.kill_turn if r.kill_turn is not None else turns + 2) for r in results}
    early = defaultdict(list)
    for r in results:
        for name, t in r.first_cast.items():
            if t <= 4:
                early[name].append(win_turn[id(r)])
    overall = _mean(list(win_turn.values())) or 0
    impacts = []
    for name, wins in early.items():
        if len(wins) >= max(10, games // 50):
            gain = overall - sum(wins) / len(wins)
            if gain > 0.15:
                impacts.append((gain, name))
    impacts.sort(reverse=True)
    key_cards = [{
        "name": name, "impact": "high" if gain >= 0.7 else "medium" if gain >= 0.3 else "low",
        "note": f"Cast by turn 4 in {len(early[name])} games; the deck won {gain:.1f} turns sooner on average when it was.",
    } for gain, name in impacts[:8]]

    # Dead cards: still in hand at the end, three or more turns after being drawn.
    drawn = Counter(n for r in results for n in r.drawn_turn)
    stuck = Counter(n for r in results for n in r.stuck)
    dead = sorted(((stuck[n] / drawn[n], n) for n in stuck if drawn[n] >= max(10, games // 50)), reverse=True)
    dead_cards = [{"name": n, "stuckRate": round(rate, 3), "note": f"Sat in hand 3+ turns in {stuck[n]} of the {drawn[n]} games it was drawn."}
                  for rate, n in dead[:8] if rate >= 0.2]

    cmd_turns = [r.commander_turn for r in results if r.commander_turn is not None]
    sample = next((r.log for r in results if r.log), [])
    method = (
        f"{games:,} goldfish games of up to {turns} turns ({fmt.name}: {fmt.life} life, "
        f"{'a free first mulligan, ' if fmt.free_mulligan else ''}London mulligans, "
        f"{'a draw on turn 1' if fmt.draw_first_turn else 'no draw on turn 1 on the play'}), simulated by {TOOL}"
        f"{f' with seed {seed}' if seed is not None else ''}. Each turn: a land, then spells in the order ramp, commander, card draw, "
        f"threats, the rest, paying mana colour by colour; everything that can attack does. Modelled from rules text: mana, "
        f"fetching lands, card draw, damage and life loss to the opponent, creature tokens, team pumps, haste and double strike. "
        + (f"Not modelled (cast, but no effect counted): {', '.join(not_modelled[:20])}{'…' if len(not_modelled) > 20 else ''}. "
           if not_modelled else "Every card's main effect was modelled. ")
        + (f"Held back as interaction (never cast: there's nothing to remove or counter): {', '.join(held_back)}."
           if held_back else "")
    )
    won_rate = _rate(len(kills), games)
    report = {
        "format": FORMAT,
        "tool": TOOL,
        "deckId": deck_id,
        "deckName": deck_name,
        "commander": commander,
        "playFormat": fmt.id,
        "games": games,
        "turns": turns,
        "method": method,
        "confidence": "high" if games >= 1000 and len(not_modelled) <= 10 else "medium" if games >= 200 else "low",
        "summary": "",
        "killTurn": {
            "average": _mean(kills),
            "median": statistics.median(kills) if kills else None,
            "wonRate": won_rate,
            "byTurn": {str(t): by_turn[t] for t in sorted(by_turn)},
        },
        "damageByTurn": per_turn("damage", carry=True),
        "landsByTurn": per_turn("lands", carry=True),
        "manaByTurn": per_turn("mana", carry=True),
        "spellsByTurn": per_turn("spells"),
        "landDropsOnCurve": _rate(on_curve, games),
        "screwRate": _rate(screw, games),
        "floodRate": _rate(flood, games),
        "mulligans": {"keepRate": _rate(sum(r.kept_seven for r in results), games), "average": _mean([r.mulligans for r in results])},
        "commanderCast": {"rate": _rate(len(cmd_turns), games) if commander else None, "averageTurn": _mean(cmd_turns)},
        "keyCards": key_cards,
        "deadCards": dead_cards,
        "combos": [],
        "strengths": [],
        "weaknesses": [],
        "suggestions": [],
        "sampleGame": sample,
        "notModelled": not_modelled,
        "heldBack": list(held_back),
    }
    return report


def markdown(r: dict) -> str:
    pct = lambda v: "–" if v is None else f"{round(v * 100)}%"  # noqa: E731
    one = lambda v: "–" if v is None else f"{v:g}"  # noqa: E731
    k = r["killTurn"]
    lines = [
        f"# Goldfish report: {r['deckName']}",
        "",
        f"{r['games']:,} games of up to {r['turns']} turns · {r['playFormat']} · confidence {r['confidence']}",
        "",
        "| | |",
        "|---|---|",
        f"| Wins by turn {r['turns']} | {pct(k['wonRate'])} |",
        f"| Average winning turn | {one(k['average'])} (median {one(k['median'])}) |",
    ]
    if r.get("commander"):
        lines.append(f"| Commander cast | {pct(r['commanderCast']['rate'])}, turn {one(r['commanderCast']['averageTurn'])} on average |")
    lines += [
        f"| Kept the opening 7 | {pct(r['mulligans']['keepRate'])} ({one(r['mulligans']['average'])} mulligans a game) |",
        f"| Land drops on curve to turn 4 | {pct(r['landDropsOnCurve'])} |",
        f"| Mana screw (under 3 lands on turn 4) | {pct(r['screwRate'])} |",
        f"| Flood (7+ lands, 1 or fewer cards in hand on turn 7) | {pct(r['floodRate'])} |",
        "",
        "**Games won on each turn:** " + (", ".join(f"turn {t}: {n}" for t, n in k["byTurn"].items()) or "none within the limit"),
        "",
        "**Average damage by the end of each turn:** " + ", ".join(one(v) for v in r["damageByTurn"]),
        "",
        "**Average mana each turn:** " + ", ".join(one(v) for v in r["manaByTurn"]),
    ]
    if r["keyCards"]:
        lines += ["", "**Cards that mattered:**"] + [f"- {c['name']} ({c['impact']}): {c['note']}" for c in r["keyCards"]]
    if r["deadCards"]:
        lines += ["", "**Cards that sat in hand:**"] + [f"- {c['name']}: {c['note']}" for c in r["deadCards"]]
    if r.get("heldBack"):
        lines += ["", f"**Held back** ({len(r['heldBack'])} interaction cards: never cast, as a goldfish opponent has nothing "
                  "to remove or counter): " + ", ".join(r["heldBack"])]
    if r["notModelled"]:
        lines += ["", f"**Not modelled** ({len(r['notModelled'])} cards: cast, but their effects weren't counted): "
                  + ", ".join(r["notModelled"])]
    lines += ["", "_Goldfish numbers: no opponent blocks, removes or counters anything. Use them to compare versions of a deck._"]
    return "\n".join(lines) + "\n"
