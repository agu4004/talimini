"""Human agent implementation using CLI prompts.

This module implements an agent that prompts a human player for input via
the command-line interface.
"""
from __future__ import annotations

from ..models import Action, GameState


class HumanAgent:
    """Agent that prompts a human player for actions via CLI.

    This agent displays the current game state and prompts the user
    to choose actions through keyboard input.

    Attributes:
        name: Display name of the agent
    """

    def __init__(self, name: str = "Human Player"):
        """Initialize the human agent.

        Args:
            name: Display name for this agent
        """
        self._name = name

    @property
    def name(self) -> str:
        """Get the agent's display name."""
        return self._name

    def reset(self) -> None:
        """Reset agent state for a new game (no-op for human agent)."""
        pass

    def choose_action(self, state: GameState) -> Action:
        """Prompt the human player to choose an action.

        Args:
            state: Current game state

        Returns:
            Action chosen by the human player

        Raises:
            KeyboardInterrupt: If user interrupts input
        """
        # Import here to avoid circular dependency
        from ..agents import HumanActionPrompter

        prompter = HumanActionPrompter(state)
        return prompter.prompt()


__all__ = ["HumanAgent"]
