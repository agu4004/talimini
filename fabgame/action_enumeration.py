"""Action enumeration module - generates all legal actions for a given game state.

This module contains the ActionEnumerator class which encapsulates the branching logic
for generating legal actions based on the current game phase and state.
"""
from __future__ import annotations

import itertools
from typing import List, Optional, Set, Tuple

from .config import DEFEND_MAX, MAX_PITCH_ENUM
from .models import Action, ActType, CombatStep, GameState, Phase


def _iter_pitch_combos(indices: List[int], max_pitch: int) -> List[Tuple[int, ...]]:
    """Generate all possible pitch combinations from a pool of card indices.

    Args:
        indices: List of card indices that can be pitched
        max_pitch: Maximum number of cards that can be pitched

    Returns:
        List of tuples, each containing a combination of card indices to pitch
    """
    combos: List[Tuple[int, ...]] = []
    if max_pitch <= 0:
        return combos
    for count in range(1, max_pitch + 1):
        combos.extend(itertools.combinations(indices, count))
    return combos


class ActionEnumerator:
    """Encapsulates the branching logic for generating legal actions.

    This class examines the current game state and generates all legal actions
    that the current actor can take based on the phase, combat step, and other
    state variables.

    Attributes:
        state: The current game state
        turn_player: The player whose turn it is
    """

    def __init__(self, state: GameState) -> None:
        """Initialize the action enumerator.

        Args:
            state: The current game state
        """
        self.state = state
        self.turn_player = state.players[state.turn]

    def enumerate(self) -> List[Action]:
        """Generate all legal actions for the current game state.

        Returns:
            List of legal Action objects that can be taken
        """
        if self.state.awaiting_arsenal:
            return self._arsenal_actions()
        if self.state.phase == Phase.SOT:
            return [Action(ActType.CONTINUE)]
        if self.state.combat_step == CombatStep.LAYER:
            return [Action(ActType.PASS)]
        if self.state.combat_step in (CombatStep.DAMAGE, CombatStep.RESOLUTION):
            return [Action(ActType.PASS)]
        if self.state.combat_step == CombatStep.REACTION:
            return self._reaction_actions()
        if self.state.phase == Phase.ACTION:
            return self._action_phase_actions()
        return []

    def _arsenal_actions(self) -> List[Action]:
        """Generate legal actions for the arsenal selection phase.

        Returns:
            List of actions: one for each card in hand that can be arsenaled, plus PASS
        """
        player_index = self.state.arsenal_player if self.state.arsenal_player is not None else self.state.turn
        arsenal_player = self.state.players[player_index]
        actions = [Action(ActType.SET_ARSENAL, play_idx=idx) for idx in range(len(arsenal_player.hand))]
        actions.append(Action(ActType.PASS))
        return actions

    @staticmethod
    def _reaction_sort_key(item: Tuple[int, Optional[int]]) -> Tuple[int, int]:
        """Sort key for reaction actions to ensure consistent ordering.

        Args:
            item: Tuple of (card_mask, arsenal_index)

        Returns:
            Sort key tuple
        """
        mask, arsenal_idx = item
        return (mask, -1 if arsenal_idx is None else arsenal_idx + 1)

    def _reaction_actions(self) -> List[Action]:
        """Generate legal actions for the reaction phase.

        Returns:
            List of reaction actions based on whether this is attack or defense reaction
        """
        actor = self.state.reaction_actor if self.state.reaction_actor is not None else 1 - self.state.turn
        if actor == 1 - self.state.turn:
            return self._defense_reaction_actions(actor)
        if self.state.last_attack_card is None:
            return [Action(ActType.PASS)]
        return self._attack_reaction_actions(actor)

    def _defense_reaction_actions(self, actor: int) -> List[Action]:
        """Generate legal defense reaction actions (reactions during blocking).

        Args:
            actor: The player index who is reacting (defender)

        Returns:
            List of DEFEND actions with various combinations of reaction cards
        """
        defending_player = self.state.players[1 - self.state.turn]
        reaction_indices = [
            i for i, card in enumerate(defending_player.hand) if card.is_defense() and card.is_reaction()
        ]
        arsenal_reactions = [
            i for i, card in enumerate(defending_player.arsenal) if card.is_defense() and card.is_reaction()
        ]
        reaction_actions: Set[Tuple[int, Optional[int]]] = set()
        max_cards = min(DEFEND_MAX, len(reaction_indices))
        for k in range(1, max_cards + 1):
            for combo in itertools.combinations(reaction_indices, k):
                mask = 0
                for idx in combo:
                    mask |= 1 << idx
                reaction_actions.add((mask, None))
                for arsenal_idx in arsenal_reactions:
                    reaction_actions.add((mask, arsenal_idx))
        for arsenal_idx in arsenal_reactions:
            reaction_actions.add((0, arsenal_idx))

        actions = [
            Action(ActType.DEFEND, play_idx=arsenal_idx, defend_mask=mask)
            if arsenal_idx is not None
            else Action(ActType.DEFEND, defend_mask=mask)
            for mask, arsenal_idx in sorted(reaction_actions, key=self._reaction_sort_key)
        ]
        actions.append(Action(ActType.PASS))
        return actions

    def _attack_reaction_actions(self, actor: int) -> List[Action]:
        """Generate legal attack reaction actions (reactions after declaring attack).

        Args:
            actor: The player index who is reacting (attacker)

        Returns:
            List of PLAY_ATTACK_REACTION actions with pitch combinations
        """
        actions: List[Action] = []
        attacking_player = self.turn_player
        float_available = self.state.floating_resources[self.state.turn]
        hand_size = len(attacking_player.hand)
        hand_reactions = [i for i, card in enumerate(attacking_player.hand) if card.is_attack_reaction()]
        arsenal_reactions = [
            i for i, card in enumerate(attacking_player.arsenal) if card.is_attack_reaction()
        ]

        for idx in hand_reactions:
            card = attacking_player.hand[idx]
            cost = card.cost
            pool = [j for j in range(hand_size) if j != idx]
            max_pitch = len(pool) if MAX_PITCH_ENUM is None else min(MAX_PITCH_ENUM, len(pool))
            needed = max(0, cost - float_available)
            if needed == 0:
                actions.append(Action(ActType.PLAY_ATTACK_REACTION, play_idx=idx, pitch_mask=0))
            else:
                for combo in _iter_pitch_combos(pool, max_pitch):
                    pitch_sum = sum(attacking_player.hand[j].pitch for j in combo)
                    if pitch_sum < needed:
                        continue
                    if any(pitch_sum - attacking_player.hand[j].pitch >= needed for j in combo):
                        continue
                    mask = 0
                    for j in combo:
                        mask |= 1 << j
                    actions.append(Action(ActType.PLAY_ATTACK_REACTION, play_idx=idx, pitch_mask=mask))

        if arsenal_reactions:
            pool = list(range(hand_size))
            max_pitch = len(pool) if MAX_PITCH_ENUM is None else min(MAX_PITCH_ENUM, len(pool))
            for idx in arsenal_reactions:
                card = attacking_player.arsenal[idx]
                cost = card.cost
                needed = max(0, cost - float_available)
                if needed == 0:
                    actions.append(Action(ActType.PLAY_ATTACK_REACTION, play_idx=-(idx + 1), pitch_mask=0))
                else:
                    for combo in _iter_pitch_combos(pool, max_pitch):
                        pitch_sum = sum(attacking_player.hand[j].pitch for j in combo)
                        if pitch_sum < needed:
                            continue
                        if any(pitch_sum - attacking_player.hand[j].pitch >= needed for j in combo):
                            continue
                        mask = 0
                        for j in combo:
                            mask |= 1 << j
                        actions.append(Action(ActType.PLAY_ATTACK_REACTION, play_idx=-(idx + 1), pitch_mask=mask))

        actions.append(Action(ActType.PASS))
        return actions

    def _action_phase_actions(self) -> List[Action]:
        """Generate legal actions for the ACTION phase.

        Returns:
            List of actions - either defense/block actions or attacker actions
        """
        if self.state.awaiting_defense:
            return self._defense_block_actions()
        return self._attacker_actions()

    def _defense_block_actions(self) -> List[Action]:
        """Generate legal blocking actions (non-reaction defense cards).

        Returns:
            List of DEFEND actions with various combinations of blocking cards
        """
        defender = self.state.players[1 - self.state.turn]
        defend_indices = [
            i for i, card in enumerate(defender.hand) if card.is_defense() and not card.is_reaction()
        ]
        actions = [Action(ActType.PASS)]
        max_cards = min(DEFEND_MAX, len(defend_indices))
        for k in range(1, max_cards + 1):
            for combo in itertools.combinations(defend_indices, k):
                mask = 0
                for idx in combo:
                    mask |= 1 << idx
                actions.append(Action(ActType.DEFEND, defend_mask=mask))
        return actions

    def _attacker_actions(self) -> List[Action]:
        """Generate all possible attacker actions (attacks from hand/arsenal/weapon).

        Returns:
            List of all possible attack actions plus PASS
        """
        actions: List[Action] = []
        float_available = self.state.floating_resources[self.state.turn]
        hand_size = len(self.turn_player.hand)

        if self.state.action_points > 0:
            actions.extend(self._attack_actions_from_hand(float_available, hand_size))

        if self.turn_player.arsenal and self.state.action_points > 0:
            actions.extend(self._attack_actions_from_arsenal(float_available, hand_size))

        if self.state.action_points > 0:
            actions.extend(self._weapon_actions(float_available, hand_size))

        actions.append(Action(ActType.PASS))
        return actions

    def _attack_actions_from_hand(self, float_available: int, hand_size: int) -> List[Action]:
        """Generate attack actions from cards in hand.

        Args:
            float_available: Amount of floating resources available
            hand_size: Number of cards in hand

        Returns:
            List of PLAY_ATTACK actions with various pitch combinations
        """
        actions: List[Action] = []
        for idx, card in enumerate(self.turn_player.hand):
            if not card.is_attack():
                continue
            cost = card.cost
            pool = [j for j in range(hand_size) if j != idx]
            max_pitch = (hand_size - 1) if MAX_PITCH_ENUM is None else min(MAX_PITCH_ENUM, hand_size - 1)
            needed = max(0, cost - float_available)
            if needed == 0:
                actions.append(Action(ActType.PLAY_ATTACK, play_idx=idx, pitch_mask=0))
                continue
            for combo in _iter_pitch_combos(pool, max_pitch):
                pitch_sum = sum(self.turn_player.hand[j].pitch for j in combo)
                if pitch_sum < needed:
                    continue
                if any(pitch_sum - self.turn_player.hand[j].pitch >= needed for j in combo):
                    continue
                mask = 0
                for j in combo:
                    mask |= 1 << j
                actions.append(Action(ActType.PLAY_ATTACK, play_idx=idx, pitch_mask=mask))
        return actions

    def _attack_actions_from_arsenal(self, float_available: int, hand_size: int) -> List[Action]:
        """Generate attack actions from cards in arsenal.

        Args:
            float_available: Amount of floating resources available
            hand_size: Number of cards in hand (for pitching)

        Returns:
            List of PLAY_ARSENAL_ATTACK actions with various pitch combinations
        """
        actions: List[Action] = []
        hand_indices = list(range(hand_size))
        max_pitch_hand = hand_size if MAX_PITCH_ENUM is None else min(MAX_PITCH_ENUM, hand_size)
        for idx, card in enumerate(self.turn_player.arsenal):
            if not card.is_attack():
                continue
            cost = card.cost
            needed = max(0, cost - float_available)
            if needed == 0:
                actions.append(Action(ActType.PLAY_ARSENAL_ATTACK, play_idx=idx, pitch_mask=0))
                continue
            for combo in _iter_pitch_combos(hand_indices, max_pitch_hand):
                pitch_sum = sum(self.turn_player.hand[j].pitch for j in combo)
                if pitch_sum < needed:
                    continue
                if any(pitch_sum - self.turn_player.hand[j].pitch >= needed for j in combo):
                    continue
                mask = 0
                for j in combo:
                    mask |= 1 << j
                actions.append(Action(ActType.PLAY_ARSENAL_ATTACK, play_idx=idx, pitch_mask=mask))
        return actions

    def _weapon_actions(self, float_available: int, hand_size: int) -> List[Action]:
        """Generate weapon attack actions.

        Args:
            float_available: Amount of floating resources available
            hand_size: Number of cards in hand (for pitching)

        Returns:
            List of WEAPON_ATTACK actions with various pitch combinations
        """
        weapon = self.turn_player.weapon
        if weapon is None:
            return []
        if weapon.once_per_turn and weapon.used_this_turn:
            return []
        indices = list(range(hand_size))
        max_pitch_weapon = hand_size if MAX_PITCH_ENUM is None else min(MAX_PITCH_ENUM, hand_size)
        needed = max(0, weapon.cost - float_available)
        actions: List[Action] = []
        if needed == 0:
            actions.append(Action(ActType.WEAPON_ATTACK, play_idx=None, pitch_mask=0))
            return actions
        for combo in _iter_pitch_combos(indices, max_pitch_weapon):
            pitch_sum = sum(self.turn_player.hand[j].pitch for j in combo)
            if pitch_sum < needed:
                continue
            if any(pitch_sum - self.turn_player.hand[j].pitch >= needed for j in combo):
                continue
            mask = 0
            for j in combo:
                mask |= 1 << j
            actions.append(Action(ActType.WEAPON_ATTACK, play_idx=None, pitch_mask=mask))
        return actions
