"""Helper functions for prompt states.

Common utilities used across different prompt states.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import GameState, CombatStep

from ...pretty import _b, _dim


def print_game_banner(state: GameState, actor_index: int) -> None:
    """Print the game state banner.

    Args:
        state: Current game state
        actor_index: Index of the acting player
    """
    from ...models import CombatStep, Phase

    print(_dim("-" * 56))
    phase_label = {"sot": "SOT", "action": "ACTION", "end": "END"}.get(
        state.phase.value, state.phase.value.upper()
    )
    await_tag = " [awaiting DEF]" if state.awaiting_defense else ""
    step_tag = ""
    if state.combat_step != CombatStep.IDLE:
        step_tag = f" | Step: {state.combat_step.name.capitalize()}"
    print(
        f"{_b('Your move')}  | Actor: P{actor_index} | Turn: P{state.turn} | Phase: {phase_label}{await_tag}{step_tag}"
    )
    print(f"Life  P0: {state.players[0].life}   P1: {state.players[1].life}")
    print(_dim("-" * 56))


def mask_from_indices(indices: list[int]) -> int:
    """Convert list of indices to bitmask.

    Args:
        indices: List of card indices

    Returns:
        Bitmask with bits set for each index
    """
    mask = 0
    for idx in indices:
        mask |= 1 << idx
    return mask


def parse_indices(prompt: str, max_idx: int) -> list[int]:
    """Parse comma-separated indices from user input.

    Args:
        prompt: Prompt message to display
        max_idx: Maximum valid index

    Returns:
        List of parsed indices
    """
    user_in = input(prompt).strip()
    if not user_in:
        return []
    parts = user_in.split(",")
    result = []
    for part in parts:
        part = part.strip()
        if part.isdigit():
            idx = int(part)
            if 0 <= idx <= max_idx:
                result.append(idx)
    return result


__all__ = ["print_game_banner", "mask_from_indices", "parse_indices"]
