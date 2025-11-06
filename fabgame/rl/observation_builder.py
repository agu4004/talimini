"""Observation space builder for RL environments.

This module provides a builder class for constructing observation spaces
in a type-safe and maintainable way, replacing hard-coded dimensions.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

try:  # pragma: no cover - dependency guard
    import numpy as np
    from gymnasium import spaces
except ImportError:  # pragma: no cover
    np = None  # type: ignore
    spaces = None  # type: ignore


class ObservationSpaceBuilder:
    """Builder for constructing RL observation spaces.

    This class provides a fluent API for building Gymnasium observation spaces
    with proper validation and type safety.

    Example:
        builder = ObservationSpaceBuilder()
        obs_space = (builder
            .add_scalar("life", low=0, high=40, player_count=2)
            .add_vector("phase", dim=4)
            .add_card_feature("hand", max_count=6, feature_dim=20, player_count=2)
            .build())
    """

    def __init__(self):
        """Initialize an empty observation space builder."""
        if spaces is None:
            raise RuntimeError("gymnasium is required for ObservationSpaceBuilder")
        self._spaces: Dict[str, spaces.Space] = {}

    def add_scalar(
        self,
        name: str,
        low: float = 0,
        high: float = 1,
        player_count: int = 1,
    ) -> "ObservationSpaceBuilder":
        """Add a scalar observation (single value per player).

        Args:
            name: Name of the observation
            low: Minimum value
            high: Maximum value
            player_count: Number of players (for multi-player observations)

        Returns:
            Self for method chaining
        """
        shape = (player_count,) if player_count > 1 else (1,)
        self._spaces[name] = spaces.Box(
            low=low, high=high, shape=shape, dtype=np.float32
        )
        return self

    def add_vector(
        self,
        name: str,
        dim: int,
        low: float = 0,
        high: float = 1,
    ) -> "ObservationSpaceBuilder":
        """Add a vector observation (fixed-size array).

        Args:
            name: Name of the observation
            dim: Dimension of the vector
            low: Minimum value for elements
            high: Maximum value for elements

        Returns:
            Self for method chaining
        """
        self._spaces[name] = spaces.Box(
            low=low, high=high, shape=(dim,), dtype=np.float32
        )
        return self

    def add_card_feature(
        self,
        name: str,
        max_count: int,
        feature_dim: int,
        player_count: int = 1,
        with_mask: bool = True,
    ) -> "ObservationSpaceBuilder":
        """Add a card feature observation (padded list of cards).

        Args:
            name: Name of the observation
            max_count: Maximum number of cards
            feature_dim: Dimension of each card's feature vector
            player_count: Number of players
            with_mask: Whether to add a corresponding mask observation

        Returns:
            Self for method chaining
        """
        # Card features
        if player_count > 1:
            shape = (player_count, max_count, feature_dim)
        else:
            shape = (max_count, feature_dim)

        self._spaces[name] = spaces.Box(
            low=-1, high=10, shape=shape, dtype=np.float32
        )

        # Optional mask
        if with_mask:
            mask_name = f"{name}_mask"
            if player_count > 1:
                mask_shape = (player_count, max_count)
            else:
                mask_shape = (max_count,)

            self._spaces[mask_name] = spaces.Box(
                low=0, high=1, shape=mask_shape, dtype=np.float32
            )

        return self

    def add_one_hot(
        self,
        name: str,
        num_classes: int,
    ) -> "ObservationSpaceBuilder":
        """Add a one-hot encoded observation.

        Args:
            name: Name of the observation
            num_classes: Number of classes (size of one-hot vector)

        Returns:
            Self for method chaining
        """
        self._spaces[name] = spaces.Box(
            low=0, high=1, shape=(num_classes,), dtype=np.float32
        )
        return self

    def add_custom(
        self,
        name: str,
        space: spaces.Space,
    ) -> "ObservationSpaceBuilder":
        """Add a custom observation space.

        Args:
            name: Name of the observation
            space: Gymnasium space object

        Returns:
            Self for method chaining
        """
        self._spaces[name] = space
        return self

    def build(self) -> spaces.Dict:
        """Build the final observation space.

        Returns:
            Gymnasium Dict space containing all added observations

        Raises:
            ValueError: If no observations have been added
        """
        if not self._spaces:
            raise ValueError("Cannot build empty observation space")
        return spaces.Dict(self._spaces)

    def get_shape_info(self) -> Dict[str, Tuple]:
        """Get shape information for all observations.

        Returns:
            Dictionary mapping observation names to their shapes
        """
        return {
            name: space.shape
            for name, space in self._spaces.items()
        }


def build_fabgame_observation_space(
    card_feature_dim: int,
    max_hand_size: int = 6,
    max_arsenal_size: int = 4,
    max_pitch_size: int = 6,
    max_grave_size: int = 60,
    hero_vocab_size: int = 10,
    phase_vocab_size: int = 4,
    combat_step_vocab_size: int = 6,
) -> spaces.Dict:
    """Build the standard observation space for Fabgame.

    This function creates the observation space with all standard features
    used by the Fabgame RL environment.

    Args:
        card_feature_dim: Dimension of card feature vectors
        max_hand_size: Maximum cards in hand
        max_arsenal_size: Maximum cards in arsenal
        max_pitch_size: Maximum cards in pitched zone
        max_grave_size: Maximum cards in graveyard
        hero_vocab_size: Size of hero vocabulary
        phase_vocab_size: Number of game phases
        combat_step_vocab_size: Number of combat steps

    Returns:
        Gymnasium Dict space for Fabgame observations
    """
    builder = ObservationSpaceBuilder()

    # Player state (2 players)
    builder.add_scalar("life", low=0, high=40, player_count=2)
    builder.add_scalar("deck_size", low=0, high=60, player_count=2)
    builder.add_scalar("grave_size", low=0, high=60, player_count=2)
    builder.add_scalar("floating_resources", low=0, high=20, player_count=2)

    # Card zones (2 players)
    builder.add_card_feature("hand", max_hand_size, card_feature_dim, player_count=2)
    builder.add_card_feature("arsenal", max_arsenal_size, card_feature_dim, player_count=2)
    builder.add_card_feature("pitched", max_pitch_size, card_feature_dim, player_count=2)
    builder.add_card_feature("grave", max_grave_size, card_feature_dim, player_count=2)

    # Hero encoding (2 players)
    builder.add_one_hot("hero", num_classes=2 * hero_vocab_size)

    # Game state
    builder.add_one_hot("phase", num_classes=phase_vocab_size)
    builder.add_one_hot("combat_step", num_classes=combat_step_vocab_size)

    # Combat state
    builder.add_scalar("pending_attack", low=0, high=20)
    builder.add_scalar("pending_damage", low=0, high=20)
    builder.add_scalar("action_points", low=0, high=5)
    builder.add_scalar("last_pitch_sum", low=0, high=20)

    # Flags
    builder.add_scalar("last_attack_had_go_again", low=0, high=1)
    builder.add_scalar("awaiting_defense", low=0, high=1)
    builder.add_scalar("awaiting_arsenal", low=0, high=1)
    builder.add_scalar("turn_player", low=0, high=1)

    # Last attack card
    builder.add_vector("last_attack_card", dim=card_feature_dim, low=-1, high=10)

    return builder.build()


__all__ = [
    "ObservationSpaceBuilder",
    "build_fabgame_observation_space",
]
