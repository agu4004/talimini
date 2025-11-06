"""Agent implementations for the Fabgame package.

This package provides different agent types that can play the game:
- Agent: Protocol defining the agent interface
- HumanAgent: Agent that prompts human players via CLI
- HeuristicAgent: Rule-based bot using simple heuristics
- MLAgent: Agent using trained ML policies (PyTorch or SB3)

All agents implement the Agent protocol and can be used interchangeably.

For backward compatibility, legacy functions are also exported:
- bot_choose_action: Heuristic bot decision function
- current_human_action: Human CLI prompt function
- HumanActionPrompter: Human prompt class
"""
from __future__ import annotations

from .base import Agent
from .heuristic import HeuristicAgent
from .human import HumanAgent
from .ml import MLAgent

# Import legacy functions for backward compatibility
from ..legacy_agents import (
    HumanActionPrompter,
    bot_choose_action,
    current_human_action,
    render_hand,
)

__all__ = [
    # New agent classes
    "Agent",
    "HumanAgent",
    "HeuristicAgent",
    "MLAgent",
    # Legacy compatibility
    "bot_choose_action",
    "current_human_action",
    "HumanActionPrompter",
    "render_hand",
]
