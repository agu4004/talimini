from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, Dict, List, NamedTuple, Optional

from .config import INTELLECT, STARTING_LIFE


@dataclass
class Card:
    name: str
    cost: int = 0
    attack: int = 0
    defense: int = 0
    pitch: int = 1
    keywords: List[str] = field(default_factory=list)
    text: str = ""
    abilities: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)

    def is_attack(self) -> bool:
        return self.attack > 0

    def is_defense(self) -> bool:
        return self.defense > 0

    def has_keyword(self, keyword: str) -> bool:
        """Return True when the card metadata includes the given keyword."""
        target = keyword.strip().lower()
        for value in self.keywords:
            if str(value).strip().lower() == target:
                return True
        return False

    def is_reaction(self) -> bool:
        """Determine if the card behaves as a (defense) reaction."""
        return self.has_keyword("reaction") or self.has_keyword("defense_reaction")

    def is_attack_reaction(self) -> bool:
        """Determine if the card is usable as an attack reaction."""
        return self.has_keyword("attack_reaction")


@dataclass
class Weapon:
    name: str
    base_attack: int
    cost: int
    once_per_turn: bool = True
    used_this_turn: bool = False
    keywords: List[str] = field(default_factory=list)

    def has_keyword(self, keyword: str) -> bool:
        """Return True when the weapon metadata includes the given keyword."""
        target = keyword.strip().lower()
        for value in self.keywords:
            if str(value).strip().lower() == target:
                return True
        return False

    def has_go_again(self) -> bool:
        """Convenience helper mirroring card lookup semantics."""
        return self.has_keyword("go_again")


@dataclass
class PlayerState:
    life: int = STARTING_LIFE
    deck: List[Card] = field(default_factory=list)
    hand: List[Card] = field(default_factory=list)
    grave: List[Card] = field(default_factory=list)
    pitched: List[Card] = field(default_factory=list)
    arsenal: List[Card] = field(default_factory=list)
    hero: str = "Generic Hero"
    weapon: Optional[Weapon] = None
    attacks_this_turn: int = 0
    hero_text: str = ""
    hero_modifiers: Dict[str, List[dict]] = field(default_factory=dict)

    def draw_up_to(self, n: int = INTELLECT) -> None:
        while len(self.hand) < n and self.deck:
            self.hand.append(self.deck.pop())

    def bottom_pitched_to_deck(self) -> None:
        while self.pitched:
            self.deck.insert(0, self.pitched.pop())


class Phase(Enum):
    SOT = "sot"
    ACTION = "action"
    REACTION = "reaction"
    END = "end"


class CombatStep(Enum):
    IDLE = "idle"
    LAYER = "layer"
    ATTACK = "attack"
    REACTION = "reaction"
    DAMAGE = "damage"
    RESOLUTION = "resolution"
    CLOSE = "close"


class ActType(IntEnum):
    CONTINUE = 0
    PLAY_ATTACK = 1
    DEFEND = 2
    PASS = 3
    WEAPON_ATTACK = 4
    SET_ARSENAL = 5
    PLAY_ARSENAL_ATTACK = 6
    PLAY_ATTACK_REACTION = 7


class Action(NamedTuple):
    typ: ActType
    play_idx: Optional[int] = None
    pitch_mask: int = 0
    defend_mask: int = 0


@dataclass
class GameState:
    players: List[PlayerState]
    turn: int
    phase: Phase
    awaiting_defense: bool = False
    awaiting_arsenal: bool = False
    arsenal_player: Optional[int] = None
    pending_attack: int = 0
    last_attack_card: Optional[Card] = None
    last_pitch_sum: int = 0
    action_points: int = 0
    last_attack_had_go_again: bool = False
    floating_resources: List[int] = field(default_factory=lambda: [0, 0])
    rng_seed: int = 0
    reaction_actor: Optional[int] = None
    reaction_block: int = 0
    reaction_arsenal_cards: List[str] = field(default_factory=list)
    combat_step: CombatStep = CombatStep.IDLE
    combat_priority: Optional[int] = None
    combat_passes: int = 0
    combat_block_total: int = 0
    pending_damage: int = 0

    def copy(self) -> "GameState":
        return copy.deepcopy(self)


@dataclass
class Game:
    state: GameState
    winner: Optional[int] = None


__all__ = [
    "Card",
    "Weapon",
    "PlayerState",
    "Phase",
    "CombatStep",
    "ActType",
    "Action",
    "GameState",
    "Game",
]
