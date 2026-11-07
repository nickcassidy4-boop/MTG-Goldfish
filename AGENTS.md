# Instructions for AI agents

This repo is a goldfish simulator for Magic: The Gathering decks, meant to be run by an AI
assistant for a user. The full instructions (the conversation, the commands, how to report) are in
[CLAUDE.md](CLAUDE.md): they apply to any assistant, not only Claude. Read it before doing anything.

In short:
1. Save the user's deck list.
2. Run `python -m goldfish check deck.txt`, and ask the questions it returns, one at a time.
3. Ask how many games (suggest 1,000).
4. Run `python -m goldfish run deck.txt ...`. On exit code 3, explain why the number of games is unusual, and ask before re-running with `--yes`.
5. Report the numbers. Never invent any.
