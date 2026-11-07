"""The command line: python -m goldfish <check|run|template> deck.txt [options]

  check     reads the deck and says what's missing (format, commander, unknown cards).
            Prints JSON; exit code 0 = ready to run, 2 = questions to ask the user.
  run       plays the games and writes the report (JSON for Deck Builder, Markdown to read).
            Exit 2 = questions to ask first; exit 3 = the number of games needs confirming
            (ask the user, then run again with --yes).
  template  writes a cards.json to fill in by hand when Scryfall can't be reached.

Run by a person in a terminal, `run` asks its questions itself (format, commander, number of
games). Run by an AI assistant (no terminal to type in), it prints them as JSON instead: see
CLAUDE.md for how an AI assistant should use these with a user.
"""
import argparse
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

from . import abilities, cards, decklist, report, rules
from .sim import Game


HELLO = """MTG Goldfish: plays a Magic: The Gathering deck many times against an opponent who does
nothing, and reports how fast and how consistently it wins.

  1. Save your deck list in a text file, e.g. deck.txt (Moxfield, Archidekt, Arena or "4 Lightning Bolt" lines).
  2. Run:   python -m goldfish run deck.txt
     It asks anything it needs (the format, your commander, how many games), then writes
     goldfish-report.md (to read) and goldfish-report.json (for Deck Builder's Play-test tab).

Other commands: check deck.txt (what's missing, as JSON), template deck.txt (card details to fill in
when Scryfall can't be reached). Using an AI assistant? Give it this repo: CLAUDE.md tells it what to do.
"""


def read_deck(path: str, renames: dict | None = None) -> decklist.DeckList:
    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    deck = decklist.parse(text)
    if renames:  # answers to "which card did you mean?" (None: leave it out)
        kept = []
        for e in deck.entries:
            if e.name in renames:
                if renames[e.name] is None:
                    continue
                e.name = renames[e.name]
            kept.append(e)
        deck.entries = kept
    return deck


def guess_format(deck, found) -> tuple[str | None, str]:
    """(format id or None, why). None means: ask the user."""
    main = [e for e in deck.entries if e.section in ("main", "commander")]
    total = sum(e.qty for e in main)
    singleton = all(e.qty == 1 or cards.key(e.name) in cards.BASICS or (found.get(cards.key(e.name)) and found[cards.key(e.name)].is_basic)
                    for e in main)
    if deck.commander_named:
        return "commander", "the list has a Commander section"
    if singleton and 95 <= total <= 101:
        return "commander", f"{total} cards, one of each"
    if 38 <= total <= 45:
        return None, f"{total} cards: probably Limited (sealed or draft), but it could be something else"
    if total >= 58:
        legal = [f for f in ("standard", "pioneer", "modern", "legacy", "vintage", "pauper")
                 if all((found.get(cards.key(e.name)) or cards.Card(e.name)).legalities.get(f) in ("legal", "restricted")
                        for e in main if found.get(cards.key(e.name)))]
        if legal:
            return None, (f"{total} cards: a 60-card deck, legal in {', '.join(legal)}. For a goldfish game these all play the "
                          f"same (20 life, no draw on turn 1), so any of them is fine")
        return None, f"{total} cards: a 60-card deck"
    return None, f"{total} cards, which doesn't match a usual format"


def examine(args) -> dict:
    """Everything check and run need: the deck, its cards, and what's missing."""
    deck = read_deck(args.deck, getattr(args, "renames", None))
    names = [e.name for e in deck.entries if e.section in ("main", "commander")]
    if args.commander:
        names.append(args.commander)
    found, unknown, error = cards.lookup(names, args.cards)
    fmt = rules.get_format(args.format)
    format_note = ""
    if args.format and not fmt:
        format_note = f"'{args.format}' isn't a format this knows."
    if not fmt:
        guessed, why = guess_format(deck, found)
        fmt = rules.get_format(guessed) if guessed else None
        format_note = format_note or why
    commander = args.commander or (deck.commander_named[0] if deck.commander_named else None)
    candidates = []
    if fmt and fmt.commander and not commander:
        candidates = [e.name for e in deck.entries if e.section in ("main", "commander")
                      and found.get(cards.key(e.name)) and found[cards.key(e.name)].can_be_commander]
    main = [e for e in deck.entries if e.section in ("main", "commander")]
    total = sum(e.qty for e in main) + (1 if args.commander and cards.key(args.commander) not in {cards.key(e.name) for e in main} else 0)

    questions, problems = [], []
    if error:
        problems.append(error)
    if unknown:
        problems.append(f"Scryfall doesn't know {len(unknown)} card name(s): {', '.join(unknown)}. Check the spelling.")
        questions.append({"id": "unknown", "ask": f"These card names weren't found: {', '.join(unknown)}. What are they called "
                          "exactly (or should they be left out)?"})
    if not fmt:
        questions.append({"id": "format", "ask": f"Which format is this deck for? ({format_note})",
                          "options": list(rules.FORMATS)})
    elif fmt.commander and not commander:
        questions.append({"id": "commander", "ask": "Which card is the commander?" + (
            f" Legendary creatures in the list: {', '.join(candidates)}." if candidates else " (It isn't marked in the list.)"),
            "options": candidates})
    if fmt:
        if fmt.exact and total != fmt.deck_size:
            problems.append(f"{fmt.name} decks have exactly {fmt.deck_size} cards; this has {total}. It can still be simulated as it is.")
        elif not fmt.exact and total < fmt.deck_size:
            problems.append(f"{fmt.name} decks have at least {fmt.deck_size} cards; this has {total}. It can still be simulated as it is.")
        if fmt.max_copies:
            over = [e.name for e in main if e.qty > fmt.max_copies and not (found.get(cards.key(e.name)) and found[cards.key(e.name)].is_basic)
                    and "any number of cards named" not in (found.get(cards.key(e.name)) or cards.Card(e.name)).oracle_text]
            if over:
                problems.append(f"More than {fmt.max_copies} of: {', '.join(over)}.")
    models = {e.name: abilities.model(found[cards.key(e.name)]) for e in main if found.get(cards.key(e.name))}
    not_modelled = sorted(n for n, m in models.items() if not m.understood)
    held_back = sorted(n for n, m in models.items() if m.interaction)
    return {
        "deck": deck, "found": found, "fmt": fmt, "commander": commander, "total": total,
        "summary": {
            "ready": not questions and not (error and len(found) < len(set(names))),
            "format": fmt.id if fmt else None,
            "formatNote": format_note,
            "commander": commander,
            "commanderCandidates": candidates,
            "cards": total,
            "unknownCards": unknown,
            "notModelled": not_modelled,
            "heldBack": held_back,
            "problems": problems,
            "questions": questions,
            "defaults": {"games": rules.DEFAULT_GAMES, "turns": rules.default_turns(fmt) if fmt else 8,
                         "sensibleGames": [rules.SENSIBLE_MIN, rules.SENSIBLE_MAX]},
        },
    }


def games_warning(games: int, per_game: float) -> dict | None:
    """Why this number of games is worth reconsidering, or None if it's sensible."""
    if games < 1 or games > rules.HARD_MAX:
        return {"games": games, "allowed": False,
                "why": f"Choose between 1 and {rules.HARD_MAX:,} games.", "suggest": rules.DEFAULT_GAMES}
    if games < rules.SENSIBLE_MIN:
        return {"games": games, "allowed": True,
                "why": (f"{games} games is a small sample: averages like the winning turn can shift by half a turn or more "
                        f"from one run to the next, and rare things (mana screw, a combo) may not show up. "
                        f"{rules.SENSIBLE_MIN:,} or more gives steadier numbers, and {rules.DEFAULT_GAMES:,} takes only a few seconds."),
                "suggest": rules.DEFAULT_GAMES}
    if games > rules.SENSIBLE_MAX:
        minutes = games * per_game / 60
        return {"games": games, "allowed": True,
                "why": (f"{games:,} games will take about {minutes:.0f} minute(s) here, and adds little: past about "
                        f"{rules.SENSIBLE_MAX:,} games the averages hardly change (the margin of error is already a few "
                        f"hundredths of a turn)."),
                "suggest": rules.SENSIBLE_MAX}
    return None


def ask(prompt: str, options: list | None = None, default: str | None = None) -> str:
    """A question in the terminal. options: numbered choices (a number or the text is accepted)."""
    if options:
        for i, o in enumerate(options, 1):
            print(f"  {i}. {o}")
    while True:
        answer = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
        if not answer and default is not None:
            return default
        if options and answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1]
        if answer:
            return answer


def interactive_questions(args) -> dict:
    """Asks the check's questions in the terminal until the deck is ready; returns examine()'s result."""
    args.renames = getattr(args, "renames", None) or {}
    while True:
        ex = examine(args)
        summary = ex["summary"]
        if summary["ready"]:
            return ex
        if not summary["questions"]:  # e.g. Scryfall unreachable: nothing a question can fix
            print("\n".join(summary["problems"]))
            raise SystemExit(1)
        q = summary["questions"][0]
        print()
        if q["id"] == "format":
            print(q["ask"])
            args.format = ask("Format", q["options"])
        elif q["id"] == "commander":
            print(q["ask"])
            args.commander = ask("Commander (a number, or type the name)", q.get("options") or None)
        elif q["id"] == "unknown":
            for name in summary["unknownCards"]:
                fixed = input(f"Scryfall doesn't know \"{name}\". Type the right name, or press Enter to leave it out: ").strip()
                args.renames[name] = fixed or None


def build_library(ex) -> tuple[list, abilities.Model | None]:
    found, fmt = ex["found"], ex["fmt"]
    commander = None
    if fmt.commander and ex["commander"]:
        c = found.get(cards.key(ex["commander"]))
        commander = abilities.model(c) if c else None
    library = []
    used_commander = False
    for e in ex["deck"].entries:
        if e.section not in ("main", "commander"):
            continue
        c = found.get(cards.key(e.name))
        if not c:
            continue
        qty = e.qty
        if commander and not used_commander and cards.key(e.name) == cards.key(commander.card.name):
            qty -= 1  # the commander starts in the command zone
            used_commander = True
        m = abilities.model(c)
        library.extend([m] * max(0, qty))
    return library, commander


def simulate(ex, games: int, turns: int, seed) -> list:
    rng = random.Random(seed)
    library, commander = build_library(ex)
    results = []
    for i in range(games):
        results.append(Game(ex["fmt"], library, commander, rng, turns, keep_log=(i == 0)).play())
    return results


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m goldfish", description="Goldfish simulator for Magic: The Gathering decks.")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("check", "run", "template"):
        s = sub.add_parser(name)
        s.add_argument("deck", help="the deck list file (or - for standard input)")
        s.add_argument("--format", help=f"one of: {', '.join(rules.FORMATS)}")
        s.add_argument("--commander", help="the commander's name (Commander decks)")
        s.add_argument("--cards", help="a JSON file of card details to use instead of Scryfall")
        if name == "run":
            s.add_argument("--games", type=int, help=f"how many games (default {rules.DEFAULT_GAMES:,}; asked in a terminal)")
            s.add_argument("--turns", type=int)
            s.add_argument("--seed", type=int, help="for repeatable results")
            s.add_argument("--yes", action="store_true", help="run an unusual number of games anyway (after asking the user)")
            s.add_argument("--name", help="the deck's name in the report")
            s.add_argument("--deck-id", help="Deck Builder's deck id, so the report can be brought back into it")
            s.add_argument("--out", default="goldfish-report.json")
            s.add_argument("--md", default="goldfish-report.md")
            s.add_argument("--no-input", action="store_true", help="never ask in the terminal: print questions as JSON (for scripts and AI)")
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("help", "hello"):
        print(HELLO)
        return 0
    args = p.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles
    except (AttributeError, ValueError):
        pass

    if args.command == "template":
        deck = read_deck(args.deck)
        names = list(dict.fromkeys(e.name for e in deck.entries))
        found, _, _ = cards.lookup(names, args.cards) if args.cards else ({}, [], None)
        out = []
        for n in names:
            c = found.get(cards.key(n))
            out.append(c.__dict__ if c else {"name": n, "mana_cost": "", "type_line": "", "oracle_text": "",
                                              "power": None, "toughness": None, "produced_mana": [], "keywords": []})
        print(json.dumps(out, indent=2))
        return 0

    ex = examine(args)
    if args.command == "check":
        print(json.dumps(ex["summary"], indent=2))
        return 0 if ex["summary"]["ready"] else 2

    # A person at a terminal (input and output both a terminal): ask, don't stop. An AI tool
    # captures the output, so it gets the questions as JSON. Windows reports an empty input
    # (NUL) as a terminal too, hence both checks and the EOFError fall-back.
    talk = sys.stdin.isatty() and sys.stdout.isatty() and not args.no_input
    if not ex["summary"]["ready"]:
        try:
            if not talk:
                raise EOFError
            ex = interactive_questions(args)
        except EOFError:
            print(json.dumps({"stopped": "questions", **examine(args)["summary"]}, indent=2))
            return 2
    fmt = ex["fmt"]
    if args.games is None:
        args.games = rules.DEFAULT_GAMES
        if talk:
            try:
                answer = ask("How many games to simulate (200 to 20,000 is sensible)", default=str(rules.DEFAULT_GAMES)).replace(",", "")
                args.games = int(answer) if answer.isdigit() else rules.DEFAULT_GAMES
            except EOFError:
                talk = False
    turns = args.turns or rules.default_turns(fmt)
    if not 1 <= turns <= rules.MAX_TURNS:
        print(json.dumps({"stopped": "turns", "why": f"Choose between 1 and {rules.MAX_TURNS} turns."}))
        return 3
    # Time a few games, for the warning and to say how long it'll take.
    start = time.perf_counter()
    simulate(ex, 20, turns, 0)
    per_game = (time.perf_counter() - start) / 20
    warning = games_warning(args.games, per_game)
    while talk and warning and not args.yes:
        print("\n" + warning["why"])
        try:
            answer = ask(f"Go ahead with {args.games:,} games? (y = yes, or type another number)" if warning["allowed"]
                         else "How many games instead", default=str(warning["suggest"]))
        except EOFError:
            talk = False
            break
        if answer.lower() in ("y", "yes") and warning["allowed"]:
            break
        if answer.replace(",", "").isdigit():
            args.games = int(answer.replace(",", ""))
            warning = games_warning(args.games, per_game)
    if warning and not talk and (not warning["allowed"] or not args.yes):
        print(json.dumps({"stopped": "games", **warning, "estimatedSeconds": round(args.games * per_game, 1)}, indent=2))
        return 3

    results = simulate(ex, args.games, turns, args.seed)
    rep = report.build(results, deck_name=args.name or Path(args.deck).stem, commander=ex["commander"] if fmt.commander else None,
                       fmt=fmt, turns=turns, seed=args.seed, not_modelled=ex["summary"]["notModelled"], deck_id=args.deck_id,
                       held_back=ex["summary"]["heldBack"])
    Path(args.out).write_text(json.dumps(rep, indent=2), encoding="utf-8")
    md = report.markdown(rep)
    Path(args.md).write_text(md, encoding="utf-8")
    print(md)
    print(f"Report: {args.out} (Deck Builder play-test JSON) and {args.md}.")
    if ex["summary"]["problems"]:
        print("Notes: " + " ".join(ex["summary"]["problems"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
