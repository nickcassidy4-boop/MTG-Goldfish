# MTG Goldfish: instructions for the AI assistant

You're helping someone play-test a Magic: The Gathering deck with this repo's simulator. It
plays hundreds or thousands of "goldfish" games (no opponent interaction) and reports how fast
and how consistently the deck wins, its mana, and the cards that matter. **Use this code; don't
write a simulator of your own.** It's already tested, and it saves you (and the user) the work.

Read this whole file before you start. Follow the conversation below in order, one question at
a time, in plain language (the user may be new to Magic and to code).

## 0. If the user just shared the repo (no deck yet)

Introduce it in a few sentences, then ask for their deck. For example:

> This is a goldfish simulator for Magic: The Gathering. Paste your deck list (from Moxfield,
> Archidekt, MTG Arena, Deck Builder or just "4 Lightning Bolt" lines) and I'll play it a
> thousand or so times against an opponent who does nothing, then tell you how fast it wins, how
> often it stumbles on mana, and which cards pull their weight. It takes a few seconds.

## 1. Get the code running

- You need **Python 3.10 or newer** and nothing else (no packages to install).
- Get the repo if you don't have it: `git clone https://github.com/nickcassidy4-boop/MTG-Goldfish.git`
  (or download and unzip `https://github.com/nickcassidy4-boop/MTG-Goldfish/archive/refs/heads/main.zip`).
  If you can't reach GitHub, ask the user to download that zip and upload it to the chat.
- Run everything from the repo's top folder: `python -m goldfish ...`.
- Card details come from **Scryfall** (api.scryfall.com). If that's blocked where you run, see
  "No internet" below.

## 2. Save the deck list

Save what the user pasted, exactly as given, to `deck.txt` (any name is fine). Don't fix it up
yourself: the simulator reads the common formats and reports anything it can't.

## 3. Check it

```
python -m goldfish check deck.txt
```

It prints JSON. `ready: true` means you can go on to step 4. Otherwise ask the user each item in
`questions`, **one at a time**, using its `ask` text (and `options`, if there are any):

- **format**: which format the deck is for. Say what you can tell from `formatNote`. For 60-card
  decks, tell them it doesn't change the results (Standard, Pioneer, Modern and the rest all play
  20 life, no draw on turn 1). Pass the answer as `--format <id>` (commander, standard, pioneer,
  modern, legacy, vintage, pauper, limited).
- **commander**: which card is the commander (Commander decks). Offer `commanderCandidates`. Pass
  it as `--commander "<exact name>"`.
- **unknown**: card names Scryfall didn't recognise. Ask how they're spelled (or whether to leave
  them out), then fix those lines in `deck.txt`.

Run `check` again with the answers until it says `ready: true`. Mention anything in `problems`
(e.g. a Commander deck that isn't exactly 100 cards): it can still be simulated as it is.

## 4. Ask how many games (and turns)

Ask how many games to simulate. Suggest **1,000** (a few seconds; steady numbers). Mention that
200 to 20,000 is the sensible range. Turns per game default to 10 for Commander and Limited, 8 for
the others (`defaults` in the check output); ask only if they want something else.

## 5. Run it

```
python -m goldfish run deck.txt --no-input --format <id> [--commander "<name>"] --games <n> [--turns <t>] --name "<deck name>"
```

- **Exit code 3** with `"stopped": "games"`: the number of games is unusual. Tell the user the
  `why` in your own words (too few: the numbers jump around from run to run; too many: it takes
  `estimatedSeconds` and adds little), suggest `suggest`, and **ask whether to go ahead or change
  it**. If they want to go ahead, run again with `--yes`. If `allowed` is false, the number is out
  of range: ask for another.
- **Exit code 2**: there are still questions (see step 3).
- **Exit code 0**: done. It printed a Markdown report and wrote `goldfish-report.json` (Deck
  Builder's play-test format) and `goldfish-report.md`.

Always add `--no-input`: without it, a run in a real terminal asks its questions there instead of
printing them for you. Add `--seed <n>` if the user wants a run they can repeat exactly.

## 6. Report back

1. Show the Markdown report (or the main numbers from it).
2. Then explain it in plain words: how fast it wins, how consistent it is, the mana, the cards that
   mattered, the cards that sat in hand. **Only use numbers from the report**; never invent any.
3. Say what wasn't modelled (`notModelled`: cast, but their effects not counted) and what was held
   back (`heldBack`: removal and the like, which a goldfish game never casts), and what that means
   for the numbers (e.g. "the deck is probably faster than this: Purphoros' damage wasn't counted").
4. Fill in the report's words, in `goldfish-report.json`: `summary` (2 to 4 sentences),
   `strengths`, `weaknesses` and up to 8 `suggestions` (`{"cut": ..., "add": ..., "why": ...}`,
   only cards legal in the deck, preferring cards the user owns if you know them). Base them on the
   numbers. Look up any card you suggest (Scryfall) rather than trusting memory.
5. Offer the JSON. In **Deck Builder** (myfirstdeckbuilder.party) it goes into a deck's Play-test
   tab: MTG helper, then Play-test it, then paste the report. It shows charts, compared with the
   last report.
6. Remind them once: these are goldfish numbers. Real opponents block and remove things, so real
   games are slower. They're best for comparing versions of the same deck.

## Changing the deck and running again

If the user swaps cards, update `deck.txt` and run again with the same games and turns, then compare
the two reports (winning turn, wins by the turn limit, screw, flood).

## No internet (Scryfall can't be reached)

`check` says it couldn't reach Scryfall. Then:

1. `python -m goldfish template deck.txt > cards.json` writes a list of the deck's cards with empty
   details.
2. Fill in each card's `mana_cost`, `type_line`, `oracle_text`, `power` and `toughness` (and
   `produced_mana` for lands, e.g. `["R"]`) **only from text you're sure of**. If you aren't sure of
   a card, ask the user to paste its text, or leave its text empty (it then counts as a vanilla
   card) and say so.
3. Add `--cards cards.json` to `check` and `run`, and mention in your report that the card text
   came from you, not Scryfall.

## What the simulator does (to explain it if asked)

See README.md, "How the games are played". In short: London mulligans (Commander's first one is
free), a land a turn, spells in the order ramp, commander, card draw, threats, then the rest, paying
mana colour by colour, then everything that can attack does. It understands mana, land fetching,
card draw, damage and life loss, tokens, team pumps (tribal lords too), haste, double strike, and
the "whenever a creature enters / attacks, deal damage" triggers. Everything else counts as cast
with no effect, and is listed.
