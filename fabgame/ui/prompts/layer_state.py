"""Layer step prompt state."""
from __future__ import annotations

from .base import PromptState
from .helpers import print_game_banner
from ...models import Action, ActType, CombatStep, GameState, Phase


class LayerState(PromptState):
    """Handles prompting during the layer priority step."""

    @property
    def name(self) -> str:
        return "Layer"

    def can_handle(self, state: GameState) -> bool:
        """Check if this is the layer step."""
        return state.phase == Phase.ACTION and state.combat_step == CombatStep.LAYER

    def prompt_action(self, state: GameState, actor_index: int) -> Action:
        """Prompt user to pass priority."""
        print_game_banner(state, actor_index)
        print("== LAYER STEP ==")
        input("Both players must pass priority to continue. Press Enter to pass... ")
        return Action(ActType.PASS)


__all__ = ["LayerState"]
