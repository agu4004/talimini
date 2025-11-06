from __future__ import annotations

"""
Reinforcement-learning utilities for fabgame.

Modules exposed:
    env                  - Gym-style environment wrapper around the engine.
    encoding             - Observation encoding helpers.
    action_mask          - Action vocabulary and legal action masking helpers.
    yaml_features        - Card metadata feature extraction from YAML definitions.
    observation_builder  - Builder for constructing observation spaces.
"""

from .action_mask import ACTION_VOCAB, ActionVocabulary, legal_action_mask
from .encoding import encode_observation, EncoderConfig
from .env import FabgameEnv, FabgameEnvState
from .observation_builder import ObservationSpaceBuilder, build_fabgame_observation_space

__all__ = [
    "ACTION_VOCAB",
    "ActionVocabulary",
    "EncoderConfig",
    "FabgameEnv",
    "FabgameEnvState",
    "encode_observation",
    "legal_action_mask",
    "ObservationSpaceBuilder",
    "build_fabgame_observation_space",
]
