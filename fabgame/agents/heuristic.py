"""Heuristic bot agent implementation.

This module implements a rule-based agent that uses simple heuristics for
decision making, such as minimizing overpitch and maximizing attack values.
"""
from __future__ import annotations

import random
from typing import Optional

from ..config import BOT_HIGH_PRIORITY_SCORE, BOT_WEAPON_TYPE_BIAS
from ..engine import current_actor_index, enumerate_legal_actions
from ..models import Action, ActType, CombatStep, GameState, Phase


class HeuristicAgent:
    """Rule-based agent using simple heuristics for decision making.

    This agent makes decisions based on:
    - Arsenal: Select card with highest attack
    - Defense: Block exactly enough to survive (minimize overpitch)
    - Attack: Choose attack with minimal cost/overpitch and maximum damage
    - Reactions: Maximize damage bonus while minimizing cost

    Attributes:
        name: Display name of the agent
        _rng: Random number generator for tie-breaking
    """

    def __init__(self, name: str = "Heuristic Bot", seed: Optional[int] = None):
        """Initialize the heuristic agent.

        Args:
            name: Display name for this agent
            seed: Random seed for deterministic behavior (optional)
        """
        self._name = name
        self._rng = random.Random(seed)

    @property
    def name(self) -> str:
        """Get the agent's display name."""
        return self._name

    def reset(self) -> None:
        """Reset agent state for a new game (no-op for heuristic agent)."""
        pass

    def choose_action(self, state: GameState) -> Action:
        """Choose an action using heuristic rules.

        Args:
            state: Current game state

        Returns:
            Selected action based on heuristic evaluation

        Raises:
            AgentError: If no legal actions are available
        """
        actions = enumerate_legal_actions(state)

        def pick_pass() -> Action:
            """Helper to find and return a PASS action."""
            for act in actions:
                if act.typ == ActType.PASS:
                    return act
            return actions[0] if actions else Action(ActType.PASS)

        # Arsenal phase: pick highest attack card
        if state.awaiting_arsenal:
            return self._choose_arsenal_action(state, actions, pick_pass)

        # Start of turn: always continue
        if state.phase == Phase.SOT:
            return actions[0] if actions else Action(ActType.PASS)

        # Defense phase: block optimally
        if state.phase == Phase.ACTION and state.combat_step == CombatStep.ATTACK and state.awaiting_defense:
            return self._choose_defense_action(state, actions, pick_pass)

        # Attack phase: choose best attack
        if state.phase == Phase.ACTION and state.combat_step in (CombatStep.IDLE, CombatStep.LAYER) and not state.awaiting_defense:
            return self._choose_attack_action(state, actions, pick_pass)

        # Reaction phase: play reactions or defend
        if state.phase == Phase.ACTION and state.combat_step == CombatStep.REACTION:
            return self._choose_reaction_action(state, actions, pick_pass)

        return pick_pass()

    def _choose_arsenal_action(self, state: GameState, actions: list[Action], pick_pass) -> Action:
        """Choose which card to set in arsenal (highest attack value).

        Args:
            state: Current game state
            actions: List of legal actions
            pick_pass: Function to get PASS action

        Returns:
            Action to set arsenal or pass
        """
        player_index = state.arsenal_player if state.arsenal_player is not None else state.turn
        arsenal_player = state.players[player_index]
        set_actions = [a for a in actions if a.typ == ActType.SET_ARSENAL and a.play_idx is not None]
        if set_actions:
            best = max(set_actions, key=lambda a: arsenal_player.hand[a.play_idx].attack)
            return best
        return pick_pass()

    def _choose_defense_action(self, state: GameState, actions: list[Action], pick_pass) -> Action:
        """Choose defense action to minimize overkill blocking.

        Args:
            state: Current game state
            actions: List of legal actions
            pick_pass: Function to get PASS action

        Returns:
            Optimal blocking action or pass
        """
        actor = current_actor_index(state)
        defender = state.players[actor]
        block_actions = [a for a in actions if a.typ == ActType.DEFEND]
        if not block_actions:
            return pick_pass()

        need = state.pending_attack

        def block_total(action: Action) -> int:
            """Calculate total block value of an action."""
            total = 0
            for i in range(len(defender.hand)):
                if (action.defend_mask >> i) & 1:
                    total += defender.hand[i].defense
            return total

        # Try to find action that blocks exactly enough
        best: Optional[Action] = None
        best_over = float("inf")
        for action in block_actions:
            total = block_total(action)
            if total >= need:
                over = total - need
                if over < best_over:
                    best_over = over
                    best = action

        # If we can block enough, use that; otherwise use maximum block
        if best is not None:
            return best
        return max(block_actions, key=block_total)

    def _choose_attack_action(self, state: GameState, actions: list[Action], pick_pass) -> Action:
        """Choose attack action with best cost/damage ratio.

        Args:
            state: Current game state
            actions: List of legal actions
            pick_pass: Function to get PASS action

        Returns:
            Best attack action or pass
        """
        turn_player = state.players[state.turn]
        hand = turn_player.hand
        weapon = turn_player.weapon
        arsenal = turn_player.arsenal

        attack_candidates = [
            a for a in actions if a.typ in (ActType.PLAY_ATTACK, ActType.PLAY_ARSENAL_ATTACK, ActType.WEAPON_ATTACK)
        ]

        if attack_candidates:
            def score(action: Action):
                """Score attack by (cost, overpitch, -attack, type_bias)."""
                pitch_sum = sum(hand[i].pitch for i in range(len(hand)) if (action.pitch_mask >> i) & 1)

                if action.typ == ActType.PLAY_ATTACK and action.play_idx is not None:
                    card = hand[action.play_idx]
                    cost = card.cost
                    attack = card.attack
                    type_bias = 0
                elif action.typ == ActType.PLAY_ARSENAL_ATTACK and action.play_idx is not None:
                    card = arsenal[action.play_idx]
                    cost = card.cost
                    attack = card.attack
                    type_bias = 1
                else:
                    if weapon is None:
                        return (BOT_HIGH_PRIORITY_SCORE, BOT_HIGH_PRIORITY_SCORE, 0, 3)
                    cost = weapon.cost
                    attack = weapon.base_attack
                    type_bias = BOT_WEAPON_TYPE_BIAS

                overpitch = pitch_sum - cost
                return (cost, overpitch, -attack, type_bias)

            attack_candidates.sort(key=score)
            return attack_candidates[0]

        return pick_pass()

    def _choose_reaction_action(self, state: GameState, actions: list[Action], pick_pass) -> Action:
        """Choose reaction action (attack or defense reactions).

        Args:
            state: Current game state
            actions: List of legal actions
            pick_pass: Function to get PASS action

        Returns:
            Best reaction action or pass
        """
        actor = current_actor_index(state)

        # Attacker reactions: maximize damage bonus
        if actor == state.turn:
            attack_player = state.players[state.turn]
            hand = attack_player.hand
            arsenal = attack_player.arsenal
            attack_reacts = [a for a in actions if a.typ == ActType.PLAY_ATTACK_REACTION]

            if attack_reacts:
                def score(action: Action):
                    """Score by (-attack_bonus, overpitch, cost)."""
                    if action.play_idx is None:
                        return (1, 0, 0)
                    if action.play_idx >= 0:
                        card = hand[action.play_idx]
                    else:
                        card = arsenal[-action.play_idx - 1]
                    pitch_sum = sum(hand[i].pitch for i in range(len(hand)) if (action.pitch_mask >> i) & 1)
                    overpitch = pitch_sum - card.cost
                    return (-card.attack, overpitch, card.cost)

                attack_reacts.sort(key=score)
                return attack_reacts[0]
            return pick_pass()

        # Defender reactions: similar to defense phase
        defend_actions = [a for a in actions if a.typ == ActType.DEFEND]
        if not defend_actions:
            return pick_pass()

        opponent = state.players[1 - state.turn]
        need = state.pending_attack

        def block_total(action: Action) -> int:
            """Calculate total block including arsenal."""
            total = 0
            for i in range(len(opponent.hand)):
                if (action.defend_mask >> i) & 1:
                    total += opponent.hand[i].defense
            if action.play_idx is not None and 0 <= action.play_idx < len(opponent.arsenal):
                total += opponent.arsenal[action.play_idx].defense
            return total

        # Try to block exactly enough
        best_full: Optional[Action] = None
        best_over = float("inf")
        for action in defend_actions:
            block = block_total(action)
            if block >= need:
                over = block - need
                if over < best_over:
                    best_over = over
                    best_full = action

        if best_full is not None:
            return best_full
        return max(defend_actions, key=block_total)


__all__ = ["HeuristicAgent"]
