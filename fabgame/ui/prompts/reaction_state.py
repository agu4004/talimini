"""Reaction phase prompt state."""
from __future__ import annotations

from typing import Optional

from .base import PromptState
from .helpers import mask_from_indices, parse_indices, print_game_banner
from ...config import DEFEND_MAX
from ...models import Action, ActType, CombatStep, GameState, Phase


class ReactionState(PromptState):
    """Handles prompting during the reaction phase."""

    @property
    def name(self) -> str:
        return "Reaction"

    def can_handle(self, state: GameState) -> bool:
        """Check if this is the reaction phase."""
        return state.phase == Phase.ACTION and state.combat_step == CombatStep.REACTION

    def prompt_action(self, state: GameState, actor_index: int) -> Action:
        """Prompt user for reaction actions."""
        # Import here to avoid circular dependency
        from ...legacy_agents import (
            _mask_from_indices,
            _prompt_pitch_sequence,
            render_arsenal,
            render_hand,
        )

        print_game_banner(state, actor_index)

        attacker_index = state.turn

        print(f"== REACTION WINDOW (you are P{actor_index}) ==")

        # Show attack information
        if state.last_attack_card is not None:
            card = state.last_attack_card
            print(f"  Attack card : {card.name}")
            print(f"  Attack value: {state.pending_attack} (base {card.attack})")
        else:
            weapon = state.players[attacker_index].weapon
            weapon_name = weapon.name if weapon else "Weapon"
            weapon_cost = weapon.cost if weapon else 0
            print(f"  Weapon attack: {weapon_name} (Cost {weapon_cost})")
            print(f"  Attack value : {state.pending_attack}")

        print(f"  Current block total: {state.reaction_block}")

        # Check if defender or attacker
        if actor_index == 1 - attacker_index:
            return self._handle_defender_reaction(state, actor_index)
        return self._handle_attacker_reaction(state, actor_index)

    def _handle_defender_reaction(self, state: GameState, actor_index: int) -> Action:
        """Handle defender reaction prompts."""
        from ...legacy_agents import _mask_from_indices, render_hand

        player = state.players[actor_index]

        print(render_hand(player))
        print("Only reaction cards may be selected.")
        print(f"Choose up to {DEFEND_MAX} cards to block (blank = no block).")

        raw_idxs = parse_indices("  Defense reaction indices: ", len(player.hand) - 1)
        idxs = [
            i
            for i in raw_idxs
            if 0 <= i < len(player.hand) and player.hand[i].is_defense() and player.hand[i].is_reaction()
        ]

        if len(idxs) > DEFEND_MAX:
            idxs = idxs[:DEFEND_MAX]

        # Check arsenal reactions
        arsenal_reactions = [
            (i, card) for i, card in enumerate(player.arsenal) if card.is_defense() and card.is_reaction()
        ]

        arsenal_choice: Optional[int] = None
        if arsenal_reactions:
            print("Arsenal defense reactions:")
            for i, card in arsenal_reactions:
                print(f"  [{i}] {card.name} (DEF:{card.defense})")
            choice = input("  Arsenal defense reaction index (blank = none): ").strip()
            if choice.isdigit():
                idx = int(choice)
                valid = {value for value, _ in arsenal_reactions}
                if idx in valid:
                    arsenal_choice = idx

        if not idxs and arsenal_choice is None:
            return Action(ActType.PASS)

        return Action(ActType.DEFEND, play_idx=arsenal_choice, defend_mask=_mask_from_indices(idxs))

    def _handle_attacker_reaction(self, state: GameState, actor_index: int) -> Action:
        """Handle attacker reaction prompts."""
        from ...legacy_agents import (
            _mask_from_indices,
            _prompt_pitch_sequence,
            render_arsenal,
            render_hand,
        )

        if state.last_attack_card is None:
            print("Attack reactions require a card attack. Passing.")
            return Action(ActType.PASS)

        player = state.players[actor_index]
        float_available = state.floating_resources[actor_index]

        print(f"Floating resources available: {float_available}")
        print("== YOUR HAND ==")
        print(render_hand(player))

        if player.arsenal:
            print("== YOUR ARSENAL ==")
            print(render_arsenal(player))

        hand_reacts = [i for i, card in enumerate(player.hand) if card.is_attack_reaction()]
        arsenal_reacts = [i for i, card in enumerate(player.arsenal) if card.is_attack_reaction()]

        options = "[P]ass"
        if hand_reacts:
            options += " / [H]and reaction"
        if arsenal_reacts:
            options += " / [R]snal reaction"

        choice = input(f"Choose: {options}: ").strip().lower()

        if not choice or choice.startswith("p"):
            return Action(ActType.PASS)

        # Hand reaction
        if choice.startswith("h") and hand_reacts:
            idx_s = input("  Hand index: ").strip()
            if not idx_s.isdigit():
                return Action(ActType.PASS)

            play_idx = int(idx_s)
            if play_idx not in hand_reacts:
                return Action(ActType.PASS)

            card = player.hand[play_idx]
            cost = card.cost

            if cost == 0:
                print("  Cost=0 -> no pitch needed.")
                return Action(ActType.PLAY_ATTACK_REACTION, play_idx=play_idx, pitch_mask=0)

            required = max(0, cost - float_available)
            if required <= 0:
                print("  Floating covers the cost.")
                return Action(ActType.PLAY_ATTACK_REACTION, play_idx=play_idx, pitch_mask=0)

            print("== SELECT PITCH FOR ATTACK REACTION ==")
            chosen = _prompt_pitch_sequence(player, required=required, forbidden=[play_idx])
            if chosen is None:
                return Action(ActType.PASS)

            return Action(ActType.PLAY_ATTACK_REACTION, play_idx=play_idx, pitch_mask=_mask_from_indices(chosen))

        # Arsenal reaction
        if choice.startswith("r") and arsenal_reacts:
            idx_s = input("  Arsenal index: ").strip()
            if not idx_s.isdigit():
                return Action(ActType.PASS)

            arsenal_idx = int(idx_s)
            if arsenal_idx not in arsenal_reacts:
                return Action(ActType.PASS)

            card = player.arsenal[arsenal_idx]
            cost = card.cost

            if cost == 0:
                print("  Cost=0 -> no pitch needed.")
                return Action(ActType.PLAY_ATTACK_REACTION, play_idx=-(arsenal_idx + 1), pitch_mask=0)

            required = max(0, cost - float_available)
            if required <= 0:
                print("  Floating covers the cost.")
                return Action(ActType.PLAY_ATTACK_REACTION, play_idx=-(arsenal_idx + 1), pitch_mask=0)

            print("== SELECT PITCH FOR ATTACK REACTION ==")
            chosen = _prompt_pitch_sequence(player, required=required)
            if chosen is None:
                return Action(ActType.PASS)

            return Action(ActType.PLAY_ATTACK_REACTION, play_idx=-(arsenal_idx + 1), pitch_mask=_mask_from_indices(chosen))

        return Action(ActType.PASS)


__all__ = ["ReactionState"]
