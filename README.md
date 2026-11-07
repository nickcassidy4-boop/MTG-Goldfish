# MTG Goldfish

A goldfish simulator for Magic: The Gathering decks, made to be run by an AI assistant
(Claude, or another) for you. Paste your deck list into the chat with a link to this repo. The
assistant asks anything it needs (the format, your commander, how many games), plays the deck
hundreds or thousands of times against an opponent who does nothing, and reports how fast and
how consistently it wins.

**AI assistants: start with [CLAUDE.md](CLAUDE.md).** It's the whole conversation, step by step.

## Using it with Claude

Paste this into a chat (Claude Code, the Claude desktop app, or claude.ai with code execution):

> Use https://github.com/nickcassidy4-boop/MTG-Goldfish to play-test my deck. Here's the list:
> *(paste your deck)*

Or just share the link, and Claude explains what to do.

## What you get

- **Speed:** the average and median winning turn, how often it wins by the turn limit, and games won on each turn.
- **Damage by turn:** average total damage dealt.
- **Mana:** lands and mana each turn, land drops on curve to turn 4, mana screw (under 3 lands on turn 4) and flood (7+ lands with 1 or fewer cards in hand on turn 7).
- **Consistency:** how often it keeps its opening seven, the average number of mulligans, and when the commander comes down.
- **Cards:** the ones that made it win sooner when cast early, and the ones that sat in hand.
- **Honesty:** the cards whose effects weren't modelled, and the removal it held back.
- **For Deck Builder:** a JSON report in the format of [Deck Builder](https://myfirstdeckbuilder.party)'s Play-test tab (`deck-builder-playtest/1`), and a Markdown summary.

## Running it yourself

Python 3.10 or newer; no packages to install. It works on its own, without an AI: in a
terminal, `run` asks you anything it needs (the format, your commander, how many games, and
whether to go ahead with an unusual number of games). Only the written summary and suggestions
are left for an AI to fill in; all the numbers are there.

```
python -m goldfish                      (how to use it)
python -m goldfish run deck.txt         (asks what it needs, then plays)
python -m goldfish check examples/krenko-commander.txt
python -m goldfish run examples/krenko-commander.txt --games 1000
python -m goldfish run examples/mono-red-60.txt --format standard --games 1000 --seed 1
```

| Command | What it does |
|---|---|
| `check deck.txt` | Reads the list and says what's missing (JSON). Exit 0: ready; 2: questions to answer. |
| `run deck.txt --games N` | Plays the games and writes `goldfish-report.json` and `goldfish-report.md`. Exit 3: the number of games needs confirming (add `--yes`). |
| `template deck.txt` | A `cards.json` to fill in by hand when Scryfall can't be reached (`--cards cards.json`). |

Options: `--no-input` (never ask in the terminal: questions come back as JSON, for scripts and AI), `--format` (commander, standard, pioneer, modern, legacy, vintage, pauper, limited),
`--commander "Name"`, `--turns`, `--seed`, `--name`, `--deck-id` (Deck Builder's), `--out`, `--md`.

Sensible numbers of games are 200 to 20,000. Fewer, and the averages jump around between runs.
More takes longer and barely changes them. About 1,000 games takes a second or two.

## How the games are played

- **The opponent** does nothing. A game is won at 0 life (40 in Commander, 20 otherwise), or with 21 commander combat damage.
- **Going first:** you're on the play. You skip the turn-1 draw, except in Commander (multiplayer rules).
- **Mulligans:** keep 7 with 2 to 5 lands and a spell costing 3 or less; otherwise mulligan. Commander's first mulligan is free, then London mulligans. Any hand of 5 or fewer cards is kept.
- **Each turn:** untap, upkeep triggers, draw, play a land (a tapped one on turn 1 when there's a choice), then cast spells in the order ramp, commander, card draw, threats, the rest. Mana is paid colour by colour from your lands and mana permanents.
- **Combat:** creatures with "{T}: make something" abilities use them instead of attacking. Everything else that can attack does: nothing blocks.
- **End of turn:** discard down to seven.
- **What's understood from rules text:**
  - mana abilities, and fetching basic lands (to the battlefield or hand);
  - drawing cards, and damage or life loss to the opponent (on cast, each turn, or "{T}:");
  - creature tokens (including "X, where X is the number of…" and "…equal to its power");
  - team and tribal pumps, team haste, haste and double strike;
  - "whenever a creature you control enters / attacks, deal damage", and "whenever this attacks" triggers.
- **Held back:** removal, counterspells and board wipes, which have nothing to hit. They're never cast.
- **Everything else** is cast for its mana cost with no effect, and listed in the report as not modelled.

Card details come from [Scryfall](https://scryfall.com), cached in `.card-cache.json`.

## Tests

```
python -m unittest discover tests
```
