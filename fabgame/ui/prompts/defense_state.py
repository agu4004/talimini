"""Defense/blocking prompt state."""
from __future__ import annotations

from .base import PromptState
from .helpers import mask_from_indices, parse_indices, print_game_banner
from ...config import DEFEND_MAX
from ...models import Action, ActType, CombatStep, GameState, Phase


class DefenseState(PromptState):
    """Handles prompting during the defense/blocking phase."""

    @property
    def name(self) -> str:
        return "Defense"

    def can_handle(self, state: GameState) -> bool:
        """Check if this is the defense phase."""
        return (
            state.phase == Phase.ACTION
            and state.combat_step == CombatStep.ATTACK
            and state.awaiting_defense
        )

    def prompt_action(self, state: GameState, actor_index: int) -> Action:
        """Prompt user to block with defense cards."""
        # Import here to avoid circular dependency
        from ...legacy_agents import render_hand

        print_game_banner(state, actor_index)

        attacker_index = state.turn
        defender = state.players[actor_index]

        print(f"== BLOCK STEP (you are P{actor_index}) ==")

        # Show attack information
        if state.last_attack_card is not None:
            card = state.last_attack_card
            print(f"  Attack card : {card.name}")
            print(f"  Attack value: {state.pending_attack} | Cost: {card.cost}")
        else:
            weapon = state.players[attacker_index].weapon
            weapon_name = weapon.name if weapon else "Weapon"
            print(f"  Weapon attack: {weapon_name}")
            print(f"  Attack value : {state.pending_attack}")

        print(render_hand(defender))
        print(f"Choose up to {DEFEND_MAX} non-reaction cards to block (blank = pass).")

        idxs = parse_indices("  Block indices: ", len(defender.hand) - 1)
        if not idxs:
            return Action(ActType.PASS)

        # Filter to only valid defense cards
        idxs = [
            i
            for i in idxs
            if 0 <= i < len(defender.hand)
            and defender.hand[i].is_defense()
            and not defender.hand[i].is_reaction()
        ]

        if not idxs:
            return Action(ActType.PASS)

        # Limit to DEFEND_MAX
        if len(idxs) > DEFEND_MAX:
            idxs = idxs[:DEFEND_MAX]

        return Action(ActType.DEFEND, defend_mask=mask_from_indices(idxs))


__all__ = ["DefenseState"]
