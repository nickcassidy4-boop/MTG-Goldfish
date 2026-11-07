"""Tests that run without network access: card details come from here, not Scryfall.

    python -m unittest discover tests
"""
import random
import unittest

from goldfish import abilities, decklist, report, rules
from goldfish.__main__ import games_warning, guess_format
from goldfish.cards import Card
from goldfish.sim import Game, parse_cost, pay


def card(name, cost="", type_line="Creature", text="", power=None, produced=(), keywords=(), legal=None):
    from goldfish.cards import mana_value
    return Card(name=name, mana_cost=cost, cmc=mana_value(cost), type_line=type_line, oracle_text=text,
                power=power, toughness=power, produced_mana=list(produced), keywords=list(keywords),
                legalities=legal or {})


MOUNTAIN = card("Mountain", type_line="Basic Land — Mountain", produced="R")
BEAR = card("Raging Bear", "{1}{R}", "Creature — Bear", power="2")
BOLT = card("Lightning Bolt", "{R}", "Instant", "Lightning Bolt deals 3 damage to any target.")
SIGN = card("Mind Stone", "{2}", "Artifact", "{T}: Add {C}.\n{1}, {T}, Sacrifice Mind Stone: Draw a card.")
KRENKO = card("Krenko, Mob Boss", "{2}{R}{R}", "Legendary Creature — Goblin Warrior",
              "{T}: Create X 1/1 red Goblin creature tokens, where X is the number of Goblins you control.", power="3")


class DeckLists(unittest.TestCase):
    def test_reads_common_exports(self):
        d = decklist.parse("Commander\n1 Krenko, Mob Boss\n\nDeck\n1 Sol Ring (C21) 263 *F* [Ramp]\n2x Lightning Bolt\n"
                           "SB: 1 Shock\nSideboard\n1 Abrade\n// note\n30 Mountain\n")
        self.assertEqual(d.commander_named, ["Krenko, Mob Boss"])
        self.assertEqual([(e.qty, e.name, e.section) for e in d.entries], [
            (1, "Krenko, Mob Boss", "commander"), (1, "Sol Ring", "main"), (2, "Lightning Bolt", "main"),
            (1, "Shock", "side"), (1, "Abrade", "side"), (30, "Mountain", "side")])

    def test_format_guess(self):
        d = decklist.parse("1 Krenko, Mob Boss\n" + "".join(f"1 Card {i}\n" for i in range(99)))
        self.assertEqual(guess_format(d, {})[0], "commander")
        d60 = decklist.parse("4 Raging Bear\n4 Lightning Bolt\n52 Mountain\n")
        fmt, why = guess_format(d60, {})
        self.assertIsNone(fmt, "a 60-card deck: ask which format")
        self.assertIn("60-card", why)


class Mana(unittest.TestCase):
    def test_costs_and_payment(self):
        self.assertEqual(parse_cost("{2}{R}{R}"), (2, ["R", "R"]))
        self.assertEqual(parse_cost("{X}{W/U}{G/P}"), (0, ["WU", "G"]))
        self.assertIsNotNone(pay(["R", "R", "C", "C"], parse_cost("{2}{R}{R}")))
        self.assertIsNone(pay(["R", "C", "C", "C"], parse_cost("{2}{R}{R}")), "two red needed")
        self.assertIsNotNone(pay(["WUBRG", "R"], parse_cost("{R}{G}")), "any-colour mana covers the green")


class Abilities(unittest.TestCase):
    def test_reads_what_cards_do(self):
        self.assertEqual(abilities.model(SIGN).mana_amount, 1)
        self.assertEqual(abilities.model(BOLT).on_cast.damage, 3)
        k = abilities.model(KRENKO)
        self.assertTrue(k.each_turn.tokens_x_creatures and k.each_turn_needs_tap)
        lord = abilities.model(card("Goblin King", "{1}{R}{R}", "Creature — Goblin", "Other Goblins get +1/+1 and have mountainwalk.", "2"))
        self.assertEqual(lord.anthem, 1)
        cultivate = abilities.model(card("Cultivate", "{2}{G}", "Sorcery", "Search your library for up to two basic land cards, "
                                         "reveal those cards, put one onto the battlefield tapped and the other into your hand, then shuffle."))
        self.assertEqual((cultivate.on_cast.ramp_lands, cultivate.on_cast.lands_to_hand), (1, 1))
        tremors = abilities.model(card("Impact Tremors", "{1}{R}", "Enchantment",
                                       "Whenever a creature you control enters, Impact Tremors deals 1 damage to each opponent."))
        self.assertEqual(tremors.per_creature_damage, 1)
        removal = abilities.model(card("Murder", "{1}{B}{B}", "Instant", "Destroy target creature."))
        self.assertTrue(removal.interaction, "removal is held back in a goldfish game")
        odd = abilities.model(card("Odd Card", "{3}", "Artifact", "Whenever you cycle a card, scry 1."))
        self.assertFalse(odd.understood, "listed as not modelled")


class Games(unittest.TestCase):
    def deck(self, spells, lands=24, size=60):
        cards_ = [abilities.model(c) for c in spells]
        return cards_ * ((size - lands) // len(cards_)) + [abilities.model(MOUNTAIN)] * lands

    def test_a_simple_deck_wins_and_counts(self):
        fmt = rules.FORMATS["standard"]
        library = self.deck([BEAR, BOLT])
        results = [Game(fmt, library, None, random.Random(i), 10, keep_log=(i == 0)).play() for i in range(200)]
        rep = report.build(results, deck_name="Test", commander=None, fmt=fmt, turns=10, seed=1, not_modelled=[])
        self.assertEqual(rep["format"], "deck-builder-playtest/1")
        self.assertGreater(rep["killTurn"]["wonRate"], 0.5)
        self.assertTrue(5 <= rep["killTurn"]["average"] <= 10, rep["killTurn"])
        self.assertEqual(len(rep["damageByTurn"]), 10)
        self.assertTrue(rep["sampleGame"] and rep["sampleGame"][0]["turn"] == 1)
        self.assertIsNone(rep["commanderCast"]["rate"])
        self.assertIn("Goldfish report", report.markdown(rep))

    def test_commander_starts_in_the_command_zone(self):
        fmt = rules.FORMATS["commander"]
        library = self.deck([BEAR, SIGN], lands=37, size=99)
        commander = abilities.model(KRENKO)
        results = [Game(fmt, library, commander, random.Random(i), 10).play() for i in range(100)]
        cast = [r.commander_turn for r in results if r.commander_turn]
        self.assertGreater(len(cast), 80)
        self.assertGreaterEqual(min(cast), 3, "4 mana: turn 3 at the earliest, with a Mind Stone")

    def test_mulligans_follow_the_format(self):
        lands_only = [abilities.model(MOUNTAIN)] * 60
        r = Game(rules.FORMATS["standard"], lands_only, None, random.Random(1), 3).play()
        self.assertEqual(r.mulligans, 2, "keeps at five or fewer cards")


class GameCount(unittest.TestCase):
    def test_warnings(self):
        self.assertIsNone(games_warning(1000, 0.001))
        few = games_warning(50, 0.001)
        self.assertTrue(few["allowed"] and "small sample" in few["why"])
        many = games_warning(50_000, 0.01)
        self.assertTrue(many["allowed"] and "minute" in many["why"])
        self.assertFalse(games_warning(0, 0.001)["allowed"])
        self.assertFalse(games_warning(rules.HARD_MAX + 1, 0.001)["allowed"])


if __name__ == "__main__":
    unittest.main()


class Api(unittest.TestCase):
    def test_simulate_from_another_program(self):
        from goldfish.api import simulate
        details = [c.__dict__ for c in (MOUNTAIN, BEAR, BOLT, SIGN, KRENKO)]
        cards_ = [{"name": "Krenko, Mob Boss", "qty": 1}, {"name": "Raging Bear", "qty": 30}, {"name": "Mind Stone", "qty": 31},
                  {"name": "Mountain", "qty": 38}]
        rep = simulate(cards=cards_, details=details, format="commander", commander="Krenko, Mob Boss", games=100, seed=1, name="T")
        self.assertEqual((rep["games"], rep["turns"], rep["commander"]), (100, 10, "Krenko, Mob Boss"))
        self.assertGreater(rep["commanderCast"]["rate"], 0.8)
        with self.assertRaises(ValueError):
            simulate(cards=cards_, details=details, format="commander", games=10)  # no commander
        with self.assertRaises(ValueError):
            simulate(cards=cards_, details=details, format="standard", games=10_000, max_games=5000)
