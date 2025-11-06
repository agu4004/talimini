"""Pitch calculation utilities.

This module provides utilities for calculating valid pitch combinations when
playing cards, eliminating code duplication across action enumeration logic.
"""
from __future__ import annotations

import itertools
from typing import Iterator, List, Optional, Tuple

from ..config import MAX_PITCH_ENUM
from ..models import PlayerState


def iter_pitch_combos(indices: List[int], max_pitch: Optional[int] = None) -> Iterator[Tuple[int, ...]]:
    """Generate all possible pitch combinations from a pool of card indices.

    Args:
        indices: List of card indices that can be pitched
        max_pitch: Maximum number of cards that can be pitched (None = unlimited)

    Yields:
        Tuples containing combinations of card indices to pitch
    """
    if max_pitch is None:
        max_pitch = len(indices) if MAX_PITCH_ENUM is None else MAX_PITCH_ENUM

    if max_pitch <= 0:
        return

    for count in range(1, min(max_pitch, len(indices)) + 1):
        yield from itertools.combinations(indices, count)


def calculate_pitch_sum(player: PlayerState, pitch_indices: Tuple[int, ...]) -> int:
    """Calculate total pitch value of given card indices.

    Args:
        player: Player state containing the hand
        pitch_indices: Indices of cards to pitch

    Returns:
        Total pitch value
    """
    return sum(player.hand[i].pitch for i in pitch_indices)


def find_minimal_pitch_combos(
    player: PlayerState,
    available_indices: List[int],
    cost_needed: int,
    max_pitch: Optional[int] = None,
) -> List[int]:
    """Find all minimal pitch combinations that meet the cost requirement.

    A minimal combination is one where no subset of the cards would be sufficient.

    Args:
        player: Player state containing the hand
        available_indices: Indices of cards available for pitching
        cost_needed: Minimum pitch value required
        max_pitch: Maximum number of cards that can be pitched

    Returns:
        List of bitmasks representing valid minimal pitch combinations
    """
    valid_masks = []

    for combo in iter_pitch_combos(available_indices, max_pitch):
        pitch_sum = calculate_pitch_sum(player, combo)

        # Skip if insufficient
        if pitch_sum < cost_needed:
            continue

        # Check if this is minimal (no subset would work)
        is_minimal = True
        for card_idx in combo:
            subset_pitch = pitch_sum - player.hand[card_idx].pitch
            if subset_pitch >= cost_needed:
                is_minimal = False
                break

        if is_minimal:
            # Convert to bitmask
            mask = 0
            for idx in combo:
                mask |= 1 << idx
            valid_masks.append(mask)

    return valid_masks


class PitchCalculator:
    """Helper class for calculating pitch combinations for a player.

    This class encapsulates pitch calculation logic with player context,
    making it easier to use in action enumeration.

    Attributes:
        player: Player state
        float_available: Floating resources available
    """

    def __init__(self, player: PlayerState, float_available: int):
        """Initialize the pitch calculator.

        Args:
            player: Player state containing cards to pitch
            float_available: Amount of floating resources available
        """
        self.player = player
        self.float_available = float_available

    def enumerate_valid_pitches(
        self,
        card_index: int,
        card_cost: int,
        max_pitch: Optional[int] = None,
    ) -> List[int]:
        """Enumerate all valid pitch combinations for playing a card.

        Args:
            card_index: Index of card being played (excluded from pitch pool)
            card_cost: Cost of the card
            max_pitch: Maximum cards that can be pitched

        Returns:
            List of bitmasks representing valid pitch combinations
        """
        # Calculate how much we need from pitching
        cost_needed = max(0, card_cost - self.float_available)

        # If we don't need to pitch, return 0 mask
        if cost_needed == 0:
            return [0]

        # Build pitch pool (all cards except the one being played)
        pitch_pool = [i for i in range(len(self.player.hand)) if i != card_index]

        # Find minimal pitch combinations
        return find_minimal_pitch_combos(
            self.player,
            pitch_pool,
            cost_needed,
            max_pitch,
        )

    def enumerate_valid_pitches_all_cards(
        self,
        card_cost: int,
        max_pitch: Optional[int] = None,
    ) -> List[int]:
        """Enumerate valid pitch combinations when all cards can be pitched.

        Used for arsenal attacks or weapon attacks where no card is excluded.

        Args:
            card_cost: Cost to pay
            max_pitch: Maximum cards that can be pitched

        Returns:
            List of bitmasks representing valid pitch combinations
        """
        cost_needed = max(0, card_cost - self.float_available)

        if cost_needed == 0:
            return [0]

        pitch_pool = list(range(len(self.player.hand)))

        return find_minimal_pitch_combos(
            self.player,
            pitch_pool,
            cost_needed,
            max_pitch,
        )


__all__ = [
    "iter_pitch_combos",
    "calculate_pitch_sum",
    "find_minimal_pitch_combos",
    "PitchCalculator",
]
