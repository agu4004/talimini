"""Base classes for prompt state pattern.

This module defines the base state class for the state pattern used in
human player prompting.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Action, GameState


class PromptState(ABC):
    """Base class for prompt states.

    Each concrete state handles prompting for a specific game phase or situation.
    """

    @abstractmethod
    def can_handle(self, state: GameState) -> bool:
        """Check if this state can handle the given game state.

        Args:
            state: Current game state

        Returns:
            True if this state should handle the prompting
        """
        ...

    @abstractmethod
    def prompt_action(self, state: GameState, actor_index: int) -> Action:
        """Prompt the user for an action.

        Args:
            state: Current game state
            actor_index: Index of the acting player

        Returns:
            Action chosen by the user
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Get the display name of this state."""
        ...


__all__ = ["PromptState"]
