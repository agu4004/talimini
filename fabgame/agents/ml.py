"""ML-based agent implementations using PyTorch and Stable Baselines3.

This module implements agents that use trained neural network policies for
decision making, with proper error handling and fallback mechanisms.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

from ..exceptions import AgentTimeoutError, MLPolicyError, PolicyLoadError
from ..models import Action, GameState

logger = logging.getLogger(__name__)


class MLAgent:
    """Agent using a trained ML policy (PyTorch or SB3).

    This agent loads a trained policy from disk and uses it to select actions.
    If the policy fails or times out, it can optionally fall back to a
    heuristic agent.

    Attributes:
        name: Display name of the agent
        policy_path: Path to the trained policy file
        use_fallback: Whether to fall back to heuristic on errors
        timeout_seconds: Maximum time allowed for action selection
        deterministic: Whether to use deterministic action selection
    """

    def __init__(
        self,
        policy_path: Optional[Path] = None,
        name: str = "ML Agent",
        use_fallback: bool = True,
        timeout_seconds: float = 0.05,
        deterministic: bool = True,
    ):
        """Initialize the ML agent.

        Args:
            policy_path: Path to trained policy file (None = auto-detect)
            name: Display name for this agent
            use_fallback: Whether to use heuristic fallback on errors
            timeout_seconds: Maximum time for action selection
            deterministic: Whether to use deterministic policy
        """
        self._name = name
        self.policy_path = policy_path
        self.use_fallback = use_fallback
        self.timeout_seconds = timeout_seconds
        self.deterministic = deterministic

        # Lazy-loaded policy objects
        self._policy = None
        self._sb3_policy = None
        self._fallback_agent = None

    @property
    def name(self) -> str:
        """Get the agent's display name."""
        return self._name

    def reset(self) -> None:
        """Reset agent state for a new game."""
        # Could add game-specific caching here if needed
        pass

    def _ensure_policy_loaded(self) -> None:
        """Ensure policy is loaded, with proper error handling.

        Raises:
            PolicyLoadError: If policy cannot be loaded
        """
        if self._policy is not None or self._sb3_policy is not None:
            return

        # Import here to avoid circular dependency and optional ML dependencies
        try:
            from ..agents_ml import load_policy, load_sb3_policy
        except ImportError as e:
            raise PolicyLoadError(f"ML dependencies not available: {e}") from e

        # Try to load policy
        if self.policy_path:
            try:
                self._policy = load_policy(self.policy_path)
                if self._policy is None:
                    self._sb3_policy = load_sb3_policy(self.policy_path)
            except Exception as e:
                raise PolicyLoadError(f"Failed to load policy from {self.policy_path}: {e}") from e
        else:
            # Auto-detect policy paths
            from ..agents_ml import _default_policy_path, _default_sb3_policy_path

            default_path = _default_policy_path()
            if default_path:
                self._policy = load_policy(default_path)

            if self._policy is None:
                sb3_path = _default_sb3_policy_path()
                if sb3_path:
                    self._sb3_policy = load_sb3_policy(sb3_path)

        if self._policy is None and self._sb3_policy is None:
            raise PolicyLoadError("No policy could be loaded from default paths")

    def _get_fallback_agent(self):
        """Get or create fallback heuristic agent."""
        if self._fallback_agent is None:
            from .heuristic import HeuristicAgent
            self._fallback_agent = HeuristicAgent(name=f"{self.name} (Fallback)")
        return self._fallback_agent

    def choose_action(self, state: GameState) -> Action:
        """Choose an action using the ML policy.

        Args:
            state: Current game state

        Returns:
            Selected action

        Raises:
            MLPolicyError: If policy fails and fallback is disabled
            AgentTimeoutError: If action selection times out and fallback is disabled
            PolicyLoadError: If policy cannot be loaded
        """
        # Import here to avoid circular dependencies
        from ..engine import current_actor_index, enumerate_legal_actions
        from ..rl import ACTION_VOCAB, EncoderConfig, encode_observation, legal_action_mask

        # Ensure policy is loaded
        try:
            self._ensure_policy_loaded()
        except PolicyLoadError as e:
            if self.use_fallback:
                logger.warning(f"Policy load failed, using fallback: {e}")
                return self._get_fallback_agent().choose_action(state)
            raise

        # Get legal actions
        legal = enumerate_legal_actions(state)
        if not legal:
            if self.use_fallback:
                return self._get_fallback_agent().choose_action(state)
            raise MLPolicyError("No legal actions available")

        # Encode observation
        mask = legal_action_mask(legal, ACTION_VOCAB)
        actor = current_actor_index(state)
        encoder_config = EncoderConfig()
        obs = encode_observation(state, acting_player=actor, config=encoder_config)

        # Select action with timeout
        start = time.perf_counter()
        try:
            if self._policy is not None:
                action_idx = self._policy.select_action(obs, mask, deterministic=self.deterministic)
            else:
                action_idx = self._sb3_policy.select_action(obs, mask, deterministic=self.deterministic)
        except Exception as e:
            error_msg = f"Policy execution failed: {e}"
            logger.error(error_msg)
            if self.use_fallback:
                logger.warning("Using fallback agent")
                return self._get_fallback_agent().choose_action(state)
            raise MLPolicyError(error_msg) from e

        elapsed = time.perf_counter() - start
        if elapsed > self.timeout_seconds:
            error_msg = f"Policy timeout ({elapsed:.3f}s > {self.timeout_seconds}s)"
            logger.warning(error_msg)
            if self.use_fallback:
                return self._get_fallback_agent().choose_action(state)
            raise AgentTimeoutError(error_msg)

        # Decode action
        try:
            chosen = ACTION_VOCAB.action_for_index(action_idx)
        except (IndexError, KeyError) as e:
            error_msg = f"Invalid action index {action_idx}: {e}"
            logger.error(error_msg)
            if self.use_fallback:
                return self._get_fallback_agent().choose_action(state)
            raise MLPolicyError(error_msg) from e

        # Validate action is legal
        if chosen not in legal:
            error_msg = f"Policy selected illegal action: {chosen}"
            logger.error(error_msg)
            if self.use_fallback:
                return self._get_fallback_agent().choose_action(state)
            raise MLPolicyError(error_msg)

        return chosen


__all__ = ["MLAgent"]
