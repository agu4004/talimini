"""Custom exceptions for the Fabgame package.

This module defines a hierarchy of exceptions for different error conditions
that can occur during gameplay, agent execution, and ML operations.
"""
from __future__ import annotations


class FabgameError(Exception):
    """Base exception for all game-related errors."""
    pass


class InvalidActionError(FabgameError):
    """Raised when an action is invalid for the current game state."""
    pass


class AgentError(FabgameError):
    """Base exception for agent-related errors."""
    pass


class AgentTimeoutError(AgentError):
    """Raised when an agent exceeds its time limit for choosing an action."""
    pass


class MLPolicyError(AgentError):
    """Raised when an ML policy fails to execute."""
    pass


class PolicyLoadError(AgentError):
    """Raised when a policy cannot be loaded from disk."""
    pass


class InvalidAgentStateError(AgentError):
    """Raised when an agent is in an invalid state for the requested operation."""
    pass


__all__ = [
    "FabgameError",
    "InvalidActionError",
    "AgentError",
    "AgentTimeoutError",
    "MLPolicyError",
    "PolicyLoadError",
    "InvalidAgentStateError",
]
