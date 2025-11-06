"""Start of Turn (SOT) prompt state."""
from __future__ import annotations

from .base import PromptState
from .helpers import print_game_banner
from ...models import Action, ActType, GameState, Phase


class StartOfTurnState(PromptState):
    """Handles prompting during the Start of Turn phase."""

    @property
    def name(self) -> str:
        return "Start of Turn"

    def can_handle(self, state: GameState) -> bool:
        """Check if this is the start of turn phase."""
        return state.phase == Phase.SOT

    def prompt_action(self, state: GameState, actor_index: int) -> Action:
        """Prompt user to continue to action phase."""
        print_game_banner(state, actor_index)
        input("SOT -> press Enter to move into ACTION... ")
        return Action(ActType.CONTINUE)


__all__ = ["StartOfTurnState"]
