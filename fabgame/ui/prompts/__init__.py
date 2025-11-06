"""Prompt state pattern implementation for human player interaction.

This package implements the state pattern for handling different prompting
scenarios during human player turns. Each state handles a specific game
phase or situation.

States:
- StartOfTurnState: SOT phase
- ArsenalState: Arsenal setting phase
- DefenseState: Blocking phase
- LayerState: Layer priority step
- AttackState: Attack action selection
- ReactionState: Reaction window
"""
from __future__ import annotations

from .arsenal_state import ArsenalState
from .attack_state import AttackState
from .base import PromptState
from .defense_state import DefenseState
from .helpers import mask_from_indices, parse_indices, print_game_banner
from .layer_state import LayerState
from .reaction_state import ReactionState
from .sot_state import StartOfTurnState
from .state_machine import StateMachinePrompter

__all__ = [
    # Base
    "PromptState",
    # States
    "StartOfTurnState",
    "ArsenalState",
    "DefenseState",
    "LayerState",
    "AttackState",
    "ReactionState",
    # State machine
    "StateMachinePrompter",
    # Helpers
    "print_game_banner",
    "mask_from_indices",
    "parse_indices",
]
