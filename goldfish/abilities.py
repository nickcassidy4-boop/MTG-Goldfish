"""What a card does, read from its rules text, in the terms a goldfish game needs.

This is deliberately simple: mana, fetching lands, drawing cards, damage and life loss to the
opponent, creature tokens, team pumps and combat keywords. Anything else is counted as cast
but has no effect, and the report lists those cards so the reader knows what wasn't modelled.
"""
import re
from dataclasses import dataclass, field

from .cards import Card

NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
           "eight": 8, "nine": 9, "ten": 10}
COLOURS = "WUBRG"
TYPE_COLOUR = {"plains": "W", "island": "U", "swamp": "B", "mountain": "R", "forest": "G"}
NUM = r"(a|an|one|two|three|four|five|six|seven|eight|nine|ten|x|\d+)"
PER_TURN = re.compile(r"^(at the beginning of (?:your|each) (?:upkeep|draw step|precombat main phase|combat|end step)"
                      r"|at the beginning of combat on your turn|\{t\}(?:, [^:]*)?:)")
ON_ATTACK = re.compile(r"^whenever ~ attacks")
CREATURE_ENTERS = re.compile(r"^whenever (?:a|another|a nontoken|another nontoken)? ?(?:\w+ )?creature (?:you control )?enters")
# Removal, counterspells and board wipes: with no opponent's cards to hit, a goldfish game holds them back.
INTERACTION = re.compile(r"\b(destroy|exile|counter|return) (target|all|each|up to)\b|\bdeals? [^.]*damage to (target|each) "
                         r"(creature|planeswalker|artifact)|\btarget (creature|artifact|enchantment|permanent|nonland|spell)\b"
                         r"|\bgain control of\b")
KEYWORDS = {"", "flying", "haste", "trample", "vigilance", "reach", "deathtouch", "lifelink", "first strike", "double strike",
            "menace", "defender", "flash", "hexproof", "indestructible", "ward", "prowess", "shroud", "protection"}


def number(word: str, x: int = 0) -> int:
    word = word.lower()
    if word == "x":
        return x
    return int(word) if word.isdigit() else NUMBERS.get(word, 1)


@dataclass
class Effects:
    """One batch of effects: when the card is cast / enters, or once per turn."""
    draw: int = 0
    damage: int = 0             # to the opponent (damage or life loss)
    tokens: int = 0
    token_power: int = 0
    tokens_x_creatures: bool = False   # "create X ... where X is the number of <creatures> you control"
    tokens_x_power: bool = False       # "create X ... where X is ~'s power"
    ramp_lands: int = 0         # basic lands onto the battlefield
    ramp_tapped: bool = True
    lands_to_hand: int = 0

    def any(self) -> bool:
        return bool(self.draw or self.damage or self.tokens or self.tokens_x_creatures or self.tokens_x_power
                    or self.ramp_lands or self.lands_to_hand)


@dataclass
class Model:
    card: Card
    mana_options: list = field(default_factory=list)  # each: a string of colours one mana can be ("G", "WUBRG", "C")
    mana_amount: int = 0        # mana made by one activation
    enters_tapped: bool = False
    on_cast: Effects = field(default_factory=Effects)
    each_turn: Effects = field(default_factory=Effects)
    each_turn_needs_tap: bool = False  # "{T}: ..." (a creature can't use it the turn it arrives)
    on_attack: Effects = field(default_factory=Effects)  # "whenever ~ attacks, ..."
    per_creature_damage: int = 0  # "whenever a creature you control enters, ... N damage to each opponent"
    per_attacker_damage: int = 0  # "whenever a creature you control attacks, ... N damage to the defending player"
    team_haste: bool = False      # "creatures (or Goblins...) you control have haste"
    anthem: int = 0             # +N power to your creatures
    power: int = 0
    haste: bool = False
    double_strike: bool = False
    understood: bool = True     # False: has rules text the simulator doesn't model
    interaction: bool = False   # removal, counterspells, wipes: held back in a goldfish game

    @property
    def is_mana_source(self) -> bool:
        return self.mana_amount > 0

    @property
    def role(self) -> str:
        """For the casting order: ramp first, then card draw, then threats, then the rest."""
        if self.card.is_land:
            return "land"
        if self.is_mana_source or self.on_cast.ramp_lands:
            return "ramp"
        if self.on_cast.draw or self.each_turn.draw:
            return "draw"
        if self.power or self.on_cast.damage or self.each_turn.damage or self.on_cast.tokens or self.each_turn.tokens \
                or self.each_turn.tokens_x_creatures or self.anthem or self.per_creature_damage or self.on_attack.any():
            return "threat"
        return "other"


def normalise(card: Card) -> str:
    text = card.oracle_text.split("\n//\n")[0]
    text = re.sub(r"\([^)]*\)", "", text)  # reminder text
    name = card.name.split(" // ")[0]
    text = text.replace(name, "~")
    if "," in name:  # "Krenko, Mob Boss" is called "Krenko" in its text
        text = text.replace(name.split(",")[0], "~")
    text = re.sub(r"\bthis (creature|artifact|enchantment|land|permanent|card)\b", "~", text, flags=re.I)
    return text.lower()


def _mana_from_text(sentence: str) -> tuple[list, int] | None:
    m = re.search(r"\{t\}(?:, [^:]*)?: add (.+?)(?:\.|$)", sentence)
    if not m:
        return None
    what = m.group(1)
    if "any color" in what or "any one color" in what:
        amount = number(re.match(r"(\w+)", what).group(1)) if re.match(r"(one|two|three)\s+mana", what) else 1
        return ["WUBRG"] * amount, amount
    syms = re.findall(r"\{([wubrgc])\}", what)
    if not syms:
        return None
    if " or " in what:
        return ["".join(dict.fromkeys(s.upper() for s in syms))], 1
    return [s.upper() for s in syms], len(syms)


def _effects(sentence: str, into: Effects) -> bool:
    found = False
    for m in re.finditer(r"draws? " + NUM + r" cards?", sentence):
        into.draw += number(m.group(1), 1)
        found = True
    for m in re.finditer(r"deals? " + NUM + r" damage to (?:any target|target player|target opponent|each opponent|"
                         r"target player or planeswalker|each player|target creature or player|that player)", sentence):
        into.damage += number(m.group(1), 2)
        found = True
    for m in re.finditer(r"(?:each opponent|target opponent|target player|that player) loses " + NUM + r" life", sentence):
        into.damage += number(m.group(1), 2)
        found = True
    for m in re.finditer(r"create a number of (\d+)/(\d+) [^.]*?creature tokens? equal to (~'s power|the number of)", sentence):
        into.token_power = int(m.group(1))
        if m.group(3) == "~'s power":
            into.tokens_x_power = True
        else:
            into.tokens_x_creatures = True
        found = True
    for m in re.finditer(r"create " + NUM + r" (\d+)/(\d+) [^.]*?creature tokens?", sentence):
        if m.group(1) == "x" and "where x is the number of" in sentence:
            into.tokens_x_creatures = True
            into.token_power = int(m.group(2))
        elif m.group(1) == "x" and "where x is ~'s power" in sentence:
            into.tokens_x_power = True
            into.token_power = int(m.group(2))
        else:
            into.tokens += number(m.group(1), 2)
            into.token_power = max(into.token_power, int(m.group(2)))
        found = True
    m = re.search(r"search your library for (?:up to )?" + NUM + r" (basic land|land|plains|island|swamp|mountain|forest)[^.]*cards?", sentence)
    if m and "battlefield" in sentence:
        n = number(m.group(1), 1)
        if "the other into your hand" in sentence or "and the rest into your hand" in sentence:
            into.ramp_lands += 1
            into.lands_to_hand += max(0, n - 1)
        else:
            into.ramp_lands += n
        into.ramp_tapped = "battlefield tapped" in sentence
        found = True
    elif m and "into your hand" in sentence:
        into.lands_to_hand += number(m.group(1), 1)
        found = True
    return found


def model(card: Card) -> Model:
    mdl = Model(card)
    mdl.haste = card.has_keyword("haste")
    mdl.double_strike = card.has_keyword("double strike")
    try:
        mdl.power = int(card.power) if card.power is not None and card.is_type("creature") else 0
    except ValueError:
        mdl.power = 0  # "*" power
    text = normalise(card)

    if card.is_land:
        produced = [c for c in card.produced_mana if c in COLOURS + "C"]
        if not produced:  # fetch lands and the like: the colours of the land types they find
            produced = [TYPE_COLOUR[t] for t in TYPE_COLOUR if t in text] or (list(COLOURS) if "basic land" in text else ["C"])
        mdl.mana_options = ["".join(produced)]
        mdl.mana_amount = 1
        if re.search(r"~ enters (the battlefield )?tapped\.", text) and "unless" not in text:
            mdl.enters_tapped = True
        return mdl

    understood_any = False
    for sentence in re.split(r"(?<=[.])\s+|\n", text):
        s = sentence.strip()
        if not s:
            continue
        mana = _mana_from_text(s)
        if mana:
            mdl.mana_options, mdl.mana_amount = mana
            understood_any = True
            continue
        # Team pumps, tribal ones too ("other Goblins you control get +1/+1"): the deck's
        # creatures are taken to share the type.
        m = re.search(r"(?:other )?(?:[\w-]+ )?(?:creatures|[\w-]+s)(?: you control)? get \+(\d+)/\+\d+(?! until)", s)
        if m:
            mdl.anthem += int(m.group(1))
            if re.search(r"(?:creatures|[\w-]+s) you control (?:get [^.]*and )?have [^.]*haste", s):
                mdl.team_haste = True
            understood_any = True
            continue
        if re.search(r"^(?:other )?(?:[\w-]+ )?(?:creatures|[\w-]+s) you control have [^.]*haste", s):
            mdl.team_haste = True
            understood_any = True
            continue
        if s.startswith("whenever a creature you control attacks") or s.startswith("whenever another creature you control attacks"):
            hit = Effects()
            if re.search(r"deals? (\d+|one|two) damage to (?:the player or planeswalker it's attacking|defending player|that player|each opponent)", s) \
                    or re.search(r"(?:defending player|each opponent) loses (\d+|one) life", s):
                m2 = re.search(r"(\d+|one|two) (?:damage|life)", s)
                mdl.per_attacker_damage += number(m2.group(1), 1) if m2 else 1
                understood_any = True
            continue
        if CREATURE_ENTERS.match(s):
            hit = Effects()
            if _effects(s, hit) and hit.damage:
                mdl.per_creature_damage += hit.damage
                understood_any = True
            continue
        if ON_ATTACK.match(s):
            if _effects(s, mdl.on_attack):
                understood_any = True
            continue
        if PER_TURN.match(s):
            if _effects(s, mdl.each_turn):
                mdl.each_turn_needs_tap = s.startswith("{t}")
                understood_any = True
            continue
        if s.startswith(("whenever", "when ~ dies", "at the beginning of")):
            continue  # other triggers: not modelled
        if _effects(s, mdl.on_cast):
            understood_any = True
    keywords_only = all(re.sub(r"\s*(from \w+|\d+)$", "", w.strip()) in KEYWORDS
                        for w in re.split(r"[,\n]", re.sub(r"\{[^}]*\}", "", text)))
    mdl.understood = understood_any or not text.strip() or keywords_only
    if not understood_any and not card.is_type("creature") and INTERACTION.search(text):
        mdl.interaction = True
        mdl.understood = True  # understood as interaction: there's nothing for it to do here
    return mdl
