"""Arsenal phase prompt state."""
from __future__ import annotations

from .base import PromptState
from .helpers import print_game_banner
from ...models import Action, ActType, GameState


class ArsenalState(PromptState):
    """Handles prompting during the arsenal setting phase."""

    @property
    def name(self) -> str:
        return "Arsenal"

    def can_handle(self, state: GameState) -> bool:
        """Check if this is the arsenal phase."""
        return state.awaiting_arsenal

    def prompt_action(self, state: GameState, actor_index: int) -> Action:
        """Prompt user to set a card in arsenal."""
        # Import here to avoid circular dependency
        from ...legacy_agents import render_arsenal, render_hand

        print_game_banner(state, actor_index)

        player_index = state.arsenal_player if state.arsenal_player is not None else state.turn
        player = state.players[player_index]

        print("== END PHASE: Arsenal ==")
        print("Hand:")
        print(render_hand(player))
        print("Arsenal (current):")
        print(render_arsenal(player))

        if not player.hand:
            print("No cards available to set. Skipping.")
            return Action(ActType.PASS)

        choice = input("Select card index to set (blank to skip): ").strip()
        if not choice or not choice.isdigit():
            return Action(ActType.PASS)

        play_idx = int(choice)
        if not (0 <= play_idx < len(player.hand)):
            return Action(ActType.PASS)

        return Action(ActType.SET_ARSENAL, play_idx=play_idx)


__all__ = ["ArsenalState"]
