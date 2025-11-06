"""Attack phase prompt state."""
from __future__ import annotations

from .base import PromptState
from .helpers import mask_from_indices, print_game_banner
from ...models import Action, ActType, CombatStep, GameState, Phase


class AttackState(PromptState):
    """Handles prompting during the attack phase."""

    @property
    def name(self) -> str:
        return "Attack"

    def can_handle(self, state: GameState) -> bool:
        """Check if this is the attack phase."""
        return (
            state.phase == Phase.ACTION
            and state.combat_step == CombatStep.IDLE
            and not state.awaiting_defense
        )

    def prompt_action(self, state: GameState, actor_index: int) -> Action:
        """Prompt user to choose an attack action."""
        # Import here to avoid circular dependency
        from ...legacy_agents import (
            _mask_from_indices,
            _prompt_pitch_sequence,
            render_arsenal,
            render_hand,
        )

        print_game_banner(state, actor_index)

        player = state.players[actor_index]
        float_available = state.floating_resources[actor_index]

        print(f"Action points remaining: {state.action_points}")
        print(f"Floating resources: {float_available}")
        print("== YOUR HAND (attacker) ==")
        print(render_hand(player))

        if player.arsenal:
            print("== YOUR ARSENAL ==")
            print(render_arsenal(player))

        if state.action_points <= 0:
            input("No action points remaining. Press Enter to pass... ")
            return Action(ActType.PASS)

        weapon = player.weapon
        weapon_ready = bool(weapon and (not weapon.once_per_turn or not weapon.used_this_turn))

        if weapon:
            status = "ready" if weapon_ready else "used"
            print(f"Weapon: {weapon.name} | ATK:{weapon.base_attack} | Cost:{weapon.cost} | {status}")

        # Build options menu
        options = "[H]and attack"
        if player.arsenal:
            options += " / [R]arsenal"
        if weapon:
            options += " / [W]eapon"
        options += " / [P]ass"

        choice = input(f"Choose: {options} ? ").strip().lower()

        if choice.startswith("p"):
            return Action(ActType.PASS)

        # Weapon attack
        if choice.startswith("w"):
            if not weapon_ready or weapon is None:
                print("  Weapon not available -> PASS.")
                return Action(ActType.PASS)
            if weapon.cost == 0:
                print("  Weapon cost=0 -> no pitch needed.")
                return Action(ActType.WEAPON_ATTACK, play_idx=None, pitch_mask=0)

            required = max(0, weapon.cost - float_available)
            if required == 0:
                print("  Floating covers the weapon cost.")
                return Action(ActType.WEAPON_ATTACK, play_idx=None, pitch_mask=0)

            print("== SELECT PITCH FOR WEAPON ==")
            print(f"  Need at least {required} pitch (after using {float_available} floating).")
            chosen = _prompt_pitch_sequence(player, required=required)
            if chosen is None:
                return Action(ActType.PASS)
            return Action(ActType.WEAPON_ATTACK, play_idx=None, pitch_mask=_mask_from_indices(chosen))

        # Arsenal attack
        if choice.startswith("r") and player.arsenal:
            arsenal_idx_s = input("  Arsenal index to attack with: ").strip()
            if not arsenal_idx_s.isdigit():
                return Action(ActType.PASS)

            arsenal_idx = int(arsenal_idx_s)
            if not (0 <= arsenal_idx < len(player.arsenal)) or not player.arsenal[arsenal_idx].is_attack():
                return Action(ActType.PASS)

            cost = player.arsenal[arsenal_idx].cost
            if cost == 0:
                print("  Cost=0 -> no pitch needed.")
                return Action(ActType.PLAY_ARSENAL_ATTACK, play_idx=arsenal_idx, pitch_mask=0)

            required = max(0, cost - float_available)
            if required == 0:
                print("  Floating covers the cost.")
                return Action(ActType.PLAY_ARSENAL_ATTACK, play_idx=arsenal_idx, pitch_mask=0)

            print("== SELECT PITCH ==")
            print(f"  Need at least {required} pitch (after using {float_available} floating).")
            chosen = _prompt_pitch_sequence(player, required=required)
            if chosen is None:
                return Action(ActType.PASS)
            return Action(ActType.PLAY_ARSENAL_ATTACK, play_idx=arsenal_idx, pitch_mask=_mask_from_indices(chosen))

        # Hand attack
        play_idx_s = input("  Hand index to attack with: ").strip()
        if not play_idx_s.isdigit():
            return Action(ActType.PASS)

        play_idx = int(play_idx_s)
        if not (0 <= play_idx < len(player.hand)) or not player.hand[play_idx].is_attack():
            return Action(ActType.PASS)

        cost = player.hand[play_idx].cost
        if cost == 0:
            print("  Cost=0 -> no pitch needed.")
            return Action(ActType.PLAY_ATTACK, play_idx=play_idx, pitch_mask=0)

        required = max(0, cost - float_available)
        if required == 0:
            print("  Floating covers the cost.")
            return Action(ActType.PLAY_ATTACK, play_idx=play_idx, pitch_mask=0)

        print("== SELECT PITCH ==")
        print(f"  Need at least {required} pitch (after using {float_available} floating).")
        chosen = _prompt_pitch_sequence(player, required=required, forbidden=[play_idx])
        if chosen is None:
            return Action(ActType.PASS)
        return Action(ActType.PLAY_ATTACK, play_idx=play_idx, pitch_mask=_mask_from_indices(chosen))


__all__ = ["AttackState"]
