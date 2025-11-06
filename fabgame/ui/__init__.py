"""UI package for the Fabgame.

This package contains UI-related modules including the main play_loop function
and the prompt state machine for human players.
"""
from __future__ import annotations

# Import play_loop and related functions from the old ui module
from ..ui_old import play_loop

__all__ = ["play_loop"]
