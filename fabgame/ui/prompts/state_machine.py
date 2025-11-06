"""State machine coordinator for human prompts.

This module implements the coordinator that manages different prompt states
and delegates to the appropriate state based on the game state.
"""
from __future__ import annotations

from typing import List

from .arsenal_state import ArsenalState
from .attack_state import AttackState
from .base import PromptState
from .defense_state import DefenseState
from .layer_state import LayerState
from .reaction_state import ReactionState
from .sot_state import StartOfTurnState
from ...engine import current_actor_index
from ...models import Action, ActType, GameState


class StateMachinePrompter:
    """State machine-based prompter for human players.

    This class uses the state pattern to handle prompting based on the
    current game state. It delegates to appropriate state handlers.

    Attributes:
        states: List of available prompt states
    """

    def __init__(self):
        """Initialize the state machine with all available states."""
        self.states: List[PromptState] = [
            StartOfTurnState(),
            ArsenalState(),
            DefenseState(),
            LayerState(),
            AttackState(),
            ReactionState(),
        ]

    def prompt(self, state: GameState) -> Action:
        """Prompt the user for an action based on the current game state.

        Args:
            state: Current game state

        Returns:
            Action chosen by the user
        """
        actor_index = current_actor_index(state)

        # Find the appropriate state handler
        for prompt_state in self.states:
            if prompt_state.can_handle(state):
                return prompt_state.prompt_action(state, actor_index)

        # Default fallback: pass
        print("Warning: No prompt state could handle the current game state. Passing.")
        return Action(ActType.PASS)


__all__ = ["StateMachinePrompter"]
