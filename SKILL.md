---
name: mtg-goldfish
description: Play-test a Magic: The Gathering deck by simulating goldfish games (no opponent interaction) and report how fast and consistently it wins, its mana (screw, flood, land drops), mulligans, commander timing and key or dead cards. Use when the user wants to play-test, simulate, goldfish or check the speed/consistency of an MTG deck list (Commander, Standard, Modern, Pioneer, Legacy, Vintage, Pauper or Limited).
---

# MTG Goldfish

Run the simulator in this folder for the user's deck. Don't write your own simulator.

Follow [CLAUDE.md](CLAUDE.md) step by step:
1. Save the deck list to `deck.txt`.
2. Run `python -m goldfish check deck.txt` and ask the user each question it returns: the format, the commander, any unknown cards.
3. Ask how many games to simulate (suggest 1,000; 200 to 20,000 is sensible).
4. Run `python -m goldfish run deck.txt --format ... --games ...`. On exit code 3, explain the `why` and ask before adding `--yes`.
5. Report the numbers from the run in plain language, with what wasn't modelled. Fill in the summary, strengths, weaknesses and suggestions in `goldfish-report.json`.

Python 3.10+, no packages. Card details come from Scryfall. Offline: see "No internet" in CLAUDE.md.
