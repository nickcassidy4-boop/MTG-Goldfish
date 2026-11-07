"""The goldfish game: one player, an opponent who does nothing, played turn by turn.

Each turn: untap, upkeep triggers, draw, play a land, cast what you can in a sensible order
(ramp, your commander, card draw, threats, the rest), use tap abilities, attack with everything
that can, then discard to seven. Mana is paid colour by colour from your lands and mana
permanents. See README.md ("How the games are played") for the full rules and the limits.
"""
import random
import re
from dataclasses import dataclass, field

from .abilities import Model
from .rules import COMMANDER_DAMAGE, Format

ROLE_ORDER = {"ramp": 0, "commander": 1, "draw": 2, "threat": 3, "other": 4}


# ── Mana ──────────────────────────────────────────────────────────────

def parse_cost(cost: str) -> tuple[int, list]:
    """'{2}{R}{R}' → (2, ['R', 'R']). Hybrid pips are their colour choices ('WU'); a Phyrexian
    pip ({G/P}) is its colour (paying life instead isn't modelled); X counts as 0."""
    generic, pips = 0, []
    for sym in re.findall(r"\{([^}]+)\}", cost.split(" // ")[0]):
        s = sym.upper()
        if s.isdigit():
            generic += int(s)
        elif s in ("X", "Y", "Z"):
            continue
        elif "/" in s:
            parts = [p for p in s.split("/") if p in "WUBRGC"]
            two = next((p for p in s.split("/") if p.isdigit()), None)
            if two and not parts:
                generic += int(two)
            else:
                pips.append("".join(parts) or "WUBRG")
        elif s in "WUBRGC":
            pips.append(s)
        elif s == "S":
            pips.append("WUBRGC")
    return generic, pips


def pay(units: list, cost: tuple[int, list]) -> list | None:
    """Indexes of the mana units that pay this cost, or None. units: each a string of the
    colours that one mana can be ('G', 'WUBRG', 'C')."""
    generic, pips = cost
    free = list(range(len(units)))
    used = []
    # The pickiest pips first, each from the unit with the fewest other uses.
    for pip in sorted(pips, key=len):
        options = [i for i in free if any(c in units[i] for c in pip)]
        if not options:
            return None
        best = min(options, key=lambda i: len(units[i]))
        free.remove(best)
        used.append(best)
    if len(free) < generic:
        return None
    free.sort(key=lambda i: len(units[i]))  # spend the least flexible mana on generic costs
    return used + free[:generic]


# ── One game ──────────────────────────────────────────────────────────

@dataclass
class Permanent:
    model: Model
    sick: bool
    commander: bool = False


@dataclass
class TurnStats:
    lands: int = 0
    mana: int = 0
    spells: int = 0
    damage: int = 0  # total so far, at the end of the turn
    hand: int = 0    # cards in hand at the end of the turn


@dataclass
class GameResult:
    mulligans: int = 0
    kept_seven: bool = True
    kill_turn: int | None = None
    commander_turn: int | None = None
    turns: list = field(default_factory=list)          # TurnStats per turn played
    first_cast: dict = field(default_factory=dict)     # card name → turn first cast
    drawn_turn: dict = field(default_factory=dict)     # card name → turn it reached your hand
    stuck: set = field(default_factory=set)            # in hand at the end, drawn 3+ turns before
    log: list = field(default_factory=list)            # [{turn, plays, damage}] (kept for one game)


class Game:
    def __init__(self, fmt: Format, library: list, commander: Model | None, rng: random.Random, turns: int,
                 keep_log: bool = False):
        self.fmt = fmt
        self.rng = rng
        self.turns = turns
        self.keep_log = keep_log
        self.deck = list(library)
        self.commander = commander
        self.commander_casts = 0
        self.library: list = []
        self.hand: list = []
        self.battlefield: list = []
        self.tokens: list = []   # [power, count, turn made]
        self.life = fmt.life
        self.commander_damage = 0
        self.turn = 0
        self.result = GameResult()
        self.plays: list = []

    # ── Setup ──
    def draw(self, n: int = 1) -> None:
        for _ in range(n):
            if not self.library:
                return
            card = self.library.pop()
            self.hand.append(card)
            self.result.drawn_turn.setdefault(card.card.name, self.turn)

    def opening_hand(self) -> None:
        mulligans = 0
        while True:
            self.library = list(self.deck)
            self.rng.shuffle(self.library)
            self.hand = []
            self.draw(7)
            to_bottom = mulligans - (1 if self.fmt.free_mulligan and mulligans else 0)
            if 7 - to_bottom <= 5 or self.keepable():
                break
            mulligans += 1
        self.result.mulligans = mulligans
        self.result.kept_seven = mulligans == 0
        for _ in range(max(0, to_bottom)):
            self.library.insert(0, self.hand.pop(self.hand.index(self.bottom_choice())))
        self.result.drawn_turn = {c.card.name: 0 for c in self.hand}

    def keepable(self) -> bool:
        lands = sum(1 for c in self.hand if c.card.is_land)
        early = any(not c.card.is_land and c.card.cmc <= 3 for c in self.hand)
        return 2 <= lands <= 5 and early

    def bottom_choice(self) -> Model:
        lands = [c for c in self.hand if c.card.is_land]
        spells = [c for c in self.hand if not c.card.is_land]
        if len(lands) > 4 or not spells:
            return lands[-1]
        return max(spells, key=lambda c: c.card.cmc)

    # ── A turn ──
    def creatures(self) -> list:
        return [p for p in self.battlefield if p.model.card.is_type("creature")]

    def anthem(self) -> int:
        return sum(p.model.anthem for p in self.battlefield)

    def team_haste(self) -> bool:
        return any(p.model.team_haste for p in self.battlefield)

    def mana_units(self, fresh_land_tapped: bool) -> list:
        units = []
        for p in self.battlefield:
            m = p.model
            if not m.is_mana_source:
                continue
            if m.card.is_land and p.sick and fresh_land_tapped:
                continue  # entered tapped this turn
            if m.card.is_type("creature") and p.sick and not m.haste:
                continue
            units.extend(m.mana_options if len(m.mana_options) == m.mana_amount else m.mana_options[:1] * m.mana_amount)
        return units

    def creatures_entered(self, n: int) -> None:
        """"Whenever a creature you control enters, deal N damage": once per creature."""
        per = sum(p.model.per_creature_damage for p in self.battlefield)
        if per and n:
            self.deal(per * n)

    def apply(self, effects, source: str, x_creatures: int = 0, x_power: int = 0) -> list:
        """Carries out effects; returns the lands it put onto the battlefield."""
        fetched = []
        if effects.draw:
            self.draw(effects.draw)
        if effects.damage:
            self.deal(effects.damage)
        made = effects.tokens + (x_creatures if effects.tokens_x_creatures else 0) + (x_power if effects.tokens_x_power else 0)
        if made:
            self.tokens.append([effects.token_power, made, self.turn])
            self.creatures_entered(made)
        for _ in range(effects.ramp_lands):
            basic = next((c for c in reversed(self.library) if c.card.is_basic and c.card.is_land), None)
            if basic:
                self.library.remove(basic)
                perm = Permanent(basic, sick=effects.ramp_tapped)
                self.battlefield.append(perm)
                fetched.append(perm)
        for _ in range(effects.lands_to_hand):
            basic = next((c for c in reversed(self.library) if c.card.is_basic and c.card.is_land), None)
            if basic:
                self.library.remove(basic)
                self.hand.append(basic)
        if effects.ramp_lands or effects.lands_to_hand:
            self.rng.shuffle(self.library)
        return fetched

    def deal(self, n: int) -> None:
        self.life -= n

    def won(self) -> bool:
        return self.life <= 0 or (self.fmt.commander and self.commander_damage >= COMMANDER_DAMAGE)

    def play_land(self) -> bool:
        lands = [c for c in self.hand if c.card.is_land]
        if not lands:
            return False
        # Early on a tapped land costs little; later, play one that can be used this turn.
        tapped_ok = self.turn == 1
        lands.sort(key=lambda c: (c.enters_tapped != tapped_ok, -len(c.mana_options[0]) if c.mana_options else 0))
        land = lands[0]
        self.hand.remove(land)
        self.battlefield.append(Permanent(land, sick=land.enters_tapped))
        self.plays.append(land.card.name + (" (tapped)" if land.enters_tapped else ""))
        return True

    def castable(self, units: list) -> list:
        """[(order key, model, from command zone, payment)] for what can be cast now."""
        options = []
        for c in self.hand:
            if c.card.is_land or c.interaction:
                continue
            paid = pay(units, parse_cost(c.card.mana_cost))
            if paid is not None:
                options.append(((ROLE_ORDER[c.role], -c.card.cmc), c, False, paid))
        if self.commander and self.commander_casts == 0:
            generic, pips = parse_cost(self.commander.card.mana_cost)
            paid = pay(units, (generic + 2 * self.commander_casts, pips))
            if paid is not None:
                options.append(((ROLE_ORDER["commander"], 0), self.commander, True, paid))
        options.sort(key=lambda o: o[0])
        return options

    def cast_spells(self, units: list) -> int:
        cast = 0
        while True:
            options = self.castable(units)
            if not options:
                return cast
            _, model, from_command, paid = options[0]
            for i in sorted(paid, reverse=True):
                units.pop(i)
            if from_command:
                self.commander_casts += 1
                self.result.commander_turn = self.result.commander_turn or self.turn
            else:
                self.hand.remove(model)
            cast += 1
            self.result.first_cast.setdefault(model.card.name, self.turn)
            self.plays.append(model.card.name + (" (commander)" if from_command else ""))
            card = model.card
            if not (card.is_type("instant") or card.is_type("sorcery")):
                perm = Permanent(model, sick=card.is_type("creature") and not model.haste, commander=from_command)
                if card.is_type("creature"):
                    self.creatures_entered(1)  # before it's on the battlefield: "another creature" triggers
                self.battlefield.append(perm)
                if model.is_mana_source and not card.is_type("creature"):
                    units.extend(model.mana_options if len(model.mana_options) == model.mana_amount
                                 else model.mana_options[:1] * model.mana_amount)
            # Lands fetched untapped can be used straight away.
            for land in self.apply(model.on_cast, card.name, self.creature_count()):
                if not land.sick:
                    units.extend(land.model.mana_options)

    def creature_count(self) -> int:
        return len(self.creatures()) + sum(t[1] for t in self.tokens)

    def take_turn(self) -> None:
        self.turn += 1
        self.plays = []
        for p in self.battlefield:
            p.sick = False
        # Upkeep and other start-of-turn triggers (not the "{T}:" ones).
        for p in list(self.battlefield):
            if p.model.each_turn.any() and not p.model.each_turn_needs_tap:
                self.apply(p.model.each_turn, p.model.card.name, self.creature_count())
        if self.turn > 1 or self.fmt.draw_first_turn:
            self.draw()
        self.play_land()
        units = self.mana_units(fresh_land_tapped=True)
        stats = TurnStats(lands=sum(1 for p in self.battlefield if p.model.card.is_land), mana=len(units))
        stats.spells = self.cast_spells(units)
        # Tap abilities that make things (e.g. "{T}: create tokens"): instead of attacking.
        used = set()
        for p in self.battlefield:
            if p.model.each_turn_needs_tap and p.model.each_turn.any() and not (p.sick and not p.model.haste):
                self.apply(p.model.each_turn, p.model.card.name, self.creature_count())
                used.add(id(p))
        # Combat: everything that can attack does (nothing blocks).
        bonus = self.anthem()
        haste = self.team_haste()
        per_attacker = sum(p.model.per_attacker_damage for p in self.battlefield)
        damage = 0
        attackers = 0
        for p in self.creatures():
            if id(p) in used or (p.sick and not (p.model.haste or haste)):
                continue
            attackers += 1
            if p.model.on_attack.any():
                self.apply(p.model.on_attack, p.model.card.name, self.creature_count(), p.model.power + bonus)
            hit = max(0, p.model.power + bonus) * (2 if p.model.double_strike else 1)
            damage += hit
            if p.commander:
                self.commander_damage += hit
        for power, count, made in self.tokens:
            if made < self.turn or haste:
                damage += max(0, power + bonus) * count
                attackers += count
        self.deal(damage + per_attacker * attackers)
        while len(self.hand) > 7:
            # Discard interaction first (useless here), then extra lands, then the most expensive.
            self.hand.remove(max(self.hand, key=lambda c: (c.interaction, c.card.is_land, c.card.cmc)))
        stats.damage = self.fmt.life - self.life
        stats.hand = len(self.hand)
        self.result.turns.append(stats)
        if self.keep_log:
            self.result.log.append({"turn": self.turn, "plays": ", ".join(self.plays) or "nothing",
                                    "damage": stats.damage - (self.result.turns[-2].damage if len(self.result.turns) > 1 else 0)})

    def play(self) -> GameResult:
        self.opening_hand()
        while self.turn < self.turns:
            self.take_turn()
            if self.won():
                self.result.kill_turn = self.turn
                break
        for c in self.hand:
            if not c.interaction and self.turn - self.result.drawn_turn.get(c.card.name, self.turn) >= 3:
                self.result.stuck.add(c.card.name)
        return self.result
