"""Base agent interface and protocol definitions.

This module defines the Agent protocol that all agent implementations must follow,
ensuring a consistent interface across human, heuristic, and ML agents.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import Action, GameState


@runtime_checkable
class Agent(Protocol):
    """Protocol defining the agent interface.

    All agents (human, heuristic, ML) must implement this protocol to ensure
    consistent behavior across the codebase.
    """

    @property
    def name(self) -> str:
        """Get the display name of this agent.

        Returns:
            Human-readable agent name (e.g., "Human Player", "Heuristic Bot", "ML Agent")
        """
        ...

    def choose_action(self, state: GameState) -> Action:
        """Choose an action given the current game state.

        Args:
            state: Current game state

        Returns:
            Action to take

        Raises:
            AgentError: If agent cannot choose a valid action
            AgentTimeoutError: If agent exceeds time limit
        """
        ...

    def reset(self) -> None:
        """Reset agent state for a new game.

        This method is called at the start of each game to clear any
        game-specific state or statistics.
        """
        ...


__all__ = ["Agent"]
