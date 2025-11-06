from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

try:  # pragma: no cover - dependency guard
    import numpy as np
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("fabgame.rl.env requires numpy to be installed") from exc

try:  # pragma: no cover - optional dependency
    import gymnasium as gym
    from gymnasium import spaces
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("fabgame.rl.env requires gymnasium to be installed") from exc

from ..engine import apply_action, enumerate_legal_actions, new_game, current_actor_index
from ..models import Action, GameState
from .action_mask import ACTION_VOCAB, ActionVocabulary, legal_action_mask
from .encoding import EncoderConfig, encode_observation


@dataclass
class FabgameEnvState:
    """Serializable snapshot of the environment."""

    state: GameState
    seed: int
    rules_version: str
    step_count: int = 0

    def clone(self) -> "FabgameEnvState":
        return FabgameEnvState(
            state=self.state.copy(),
            seed=self.seed,
            rules_version=self.rules_version,
            step_count=self.step_count,
        )


class FabgameEnv(gym.Env):
    """Gymnasium-style wrapper around the fabgame engine for SB3 compatibility."""

    def __init__(
        self,
        *,
        rules_version: str = "standard",
        encoder_config: Optional[EncoderConfig] = None,
        action_vocab: Optional[ActionVocabulary] = None,
        reward_win: float = 1.0,
        reward_loss: float = -1.0,
        reward_draw: float = 0.0,
        reward_step: float = 0.0,
        reward_on_hit: float = 0.0,
        reward_good_block: float = 0.0,
        reward_overpitch: float = 0.0,
        max_episode_steps: int = 500,  # NEW: Prevent infinite games
        seed: Optional[int] = None,
        deck0: Optional[list] = None,
        deck1: Optional[list] = None,
        hero0: Optional[Any] = None,
        hero1: Optional[Any] = None,
        arena0: Optional[Any] = None,
        arena1: Optional[Any] = None,
    ) -> None:
        super().__init__()
        self.rules_version = rules_version
        self.encoder_config = encoder_config or EncoderConfig()
        self.action_vocab = action_vocab or ACTION_VOCAB
        self.reward_win = reward_win
        self.reward_loss = reward_loss
        self.reward_draw = reward_draw
        self.reward_step = reward_step
        self.reward_on_hit = reward_on_hit
        self.reward_good_block = reward_good_block
        self.reward_overpitch = reward_overpitch
        self.max_episode_steps = max_episode_steps  # NEW: Store max steps
        self._deck0 = deck0
        self._deck1 = deck1
        self._hero0 = hero0
        self._hero1 = hero1
        self._arena0 = arena0
        self._arena1 = arena1
        self._rng = random.Random(seed)
        self._seed = seed or self._rng.randrange(1, 1 << 30)
        self._state: Optional[GameState] = None
        self._done = False
        self._step_count = 0

        # Define Gymnasium spaces
        self.action_space = spaces.Discrete(len(self.action_vocab))

        # Calculate observation space dimensions
        card_feature_dim = self._get_card_feature_dim()

        # Import vocabularies from encoding module
        from .encoding import PHASE_VOCAB, COMBAT_STEP_VOCAB

        obs_spaces = {
            "life": spaces.Box(low=0, high=40, shape=(2,), dtype=np.float32),
            "deck_size": spaces.Box(low=0, high=60, shape=(2,), dtype=np.float32),
            "grave_size": spaces.Box(low=0, high=60, shape=(2,), dtype=np.float32),
            "floating_resources": spaces.Box(low=0, high=20, shape=(2,), dtype=np.float32),
            "hand": spaces.Box(low=-1, high=10, shape=(2, self.encoder_config.max_hand_size, card_feature_dim), dtype=np.float32),
            "hand_mask": spaces.Box(low=0, high=1, shape=(2, self.encoder_config.max_hand_size), dtype=np.float32),
            "arsenal": spaces.Box(low=-1, high=10, shape=(2, self.encoder_config.max_arsenal_size, card_feature_dim), dtype=np.float32),
            "arsenal_mask": spaces.Box(low=0, high=1, shape=(2, self.encoder_config.max_arsenal_size), dtype=np.float32),
            "pitched": spaces.Box(low=-1, high=10, shape=(2, self.encoder_config.max_pitch_size, card_feature_dim), dtype=np.float32),
            "pitched_mask": spaces.Box(low=0, high=1, shape=(2, self.encoder_config.max_pitch_size), dtype=np.float32),
            "grave": spaces.Box(low=-1, high=10, shape=(2, self.encoder_config.max_grave_size, card_feature_dim), dtype=np.float32),
            "grave_mask": spaces.Box(low=0, high=1, shape=(2, self.encoder_config.max_grave_size), dtype=np.float32),
            "hero": spaces.Box(low=0, high=1, shape=(2, len(self.encoder_config.hero_vocab)), dtype=np.float32),
            "phase": spaces.Box(low=0, high=1, shape=(len(PHASE_VOCAB),), dtype=np.float32),
            "combat_step": spaces.Box(low=0, high=1, shape=(len(COMBAT_STEP_VOCAB),), dtype=np.float32),
            "pending_attack": spaces.Box(low=0, high=20, shape=(1,), dtype=np.float32),
            "pending_damage": spaces.Box(low=0, high=20, shape=(1,), dtype=np.float32),
            "action_points": spaces.Box(low=0, high=5, shape=(1,), dtype=np.float32),
            "last_pitch_sum": spaces.Box(low=0, high=20, shape=(1,), dtype=np.float32),
            "last_attack_had_go_again": spaces.Box(low=0, high=1, shape=(1,), dtype=np.float32),
            "awaiting_defense": spaces.Box(low=0, high=1, shape=(1,), dtype=np.float32),
            "awaiting_arsenal": spaces.Box(low=0, high=1, shape=(1,), dtype=np.float32),
            "turn_player": spaces.Box(low=0, high=1, shape=(1,), dtype=np.float32),
            "last_attack_card": spaces.Box(low=-1, high=10, shape=(card_feature_dim,), dtype=np.float32),
        }
        self.observation_space = spaces.Dict(obs_spaces)

    def _get_card_feature_dim(self) -> int:
        """Calculate the dimension of card feature vectors."""
        base_numeric = 4  # attack, defense, cost, pitch
        flag_features = 4  # is_attack, is_defense, is_reaction, is_attack_reaction
        keyword_vocab_size = len(self.encoder_config.keyword_vocab)
        rule_trigger_size = len(self.encoder_config.rule_trigger_vocab)
        rule_duration_size = len(self.encoder_config.rule_duration_vocab)
        rule_keyword_size = len(self.encoder_config.rule_keyword_vocab)
        return base_numeric + flag_features + keyword_vocab_size + rule_trigger_size + rule_duration_size + rule_keyword_size

    @property
    def state(self) -> GameState:
        if self._state is None:
            raise RuntimeError("Environment has not been reset yet.")
        return self._state

    def reset(
        self,
        *,
        seed: Optional[int] = None,
        options: Optional[Dict[str, Any]] = None,
        deck0: Optional[list] = None,
        deck1: Optional[list] = None,
        hero0: Optional[Any] = None,
        hero1: Optional[Any] = None,
        arena0: Optional[Any] = None,
        arena1: Optional[Any] = None,
    ) -> Tuple[Dict[str, np.ndarray], Dict[str, Any]]:
        # Handle SB3-style reset parameters
        if options is not None:
            seed = options.get("seed", seed)
            deck0 = options.get("deck0", deck0)
            deck1 = options.get("deck1", deck1)
            hero0 = options.get("hero0", hero0)
            hero1 = options.get("hero1", hero1)
            arena0 = options.get("arena0", arena0)
            arena1 = options.get("arena1", arena1)

        seed = seed if seed is not None else self._rng.randrange(1, 1 << 30)
        self._seed = seed
        game = new_game(
            seed=seed,
            deck0=deck0 or self._deck0,
            deck1=deck1 or self._deck1,
            hero0=hero0 or self._hero0,
            hero1=hero1 or self._hero1,
            arena0=arena0 or self._arena0,
            arena1=arena1 or self._arena1,
        )
        self._state = game.state
        self._done = False
        self._step_count = 0
        obs = encode_observation(self.state, config=self.encoder_config)
        actions = self.legal_actions()
        info = {
            "legal_actions": actions,
            "legal_action_mask": legal_action_mask(actions, self.action_vocab),
            "actor": current_actor_index(self.state),
            "rules_version": self.rules_version,
            "seed": self._seed,
            "events": {},
            "reset": True,
        }
        return obs, info

    def legal_actions(self) -> List[Action]:
        return list(enumerate_legal_actions(self.state))

    @property
    def legal_action_mask(self) -> np.ndarray:
        """Return action mask for SB3 action masking."""
        return legal_action_mask(self.legal_actions(), self.action_vocab)

    def action_masks(self) -> np.ndarray:
        """Return action mask for SB3 action masking."""
        return self.legal_action_mask

    def _resolve_action(self, action: Union[int, Action, Dict[str, Any]]) -> Action:
        if isinstance(action, Action):
            return action
        if isinstance(action, (int, np.integer)):
            return self.action_vocab.action_for_index(int(action))
        if isinstance(action, dict):
            return Action(
                action.get("typ"),
                action.get("play_idx"),
                action.get("pitch_mask", 0),
                action.get("defend_mask", 0),
            )
        raise TypeError(f"Unsupported action type: {type(action)!r}")

    def step(
        self,
        action: Union[int, Action, Dict[str, Any]],
    ) -> Tuple[Dict[str, np.ndarray], float, bool, bool, Dict[str, Any]]:
        if self._done:
            raise RuntimeError("Cannot call step() once the episode has finished. Call reset().")

        actor = current_actor_index(self.state)
        resolved = self._resolve_action(action)
        legal = self.legal_actions()
        if resolved not in legal:
            raise ValueError(f"Illegal action attempted: {resolved!r}")
        next_state, done, events = apply_action(self.state, resolved)
        self._state = next_state
        self._done = done
        self._step_count += 1

        opponent = 1 - actor
        reward = self.reward_step  # Step penalty to encourage faster wins

        # Check for on-hit effects
        if events and "damage_dealt" in events:
            damage = events["damage_dealt"]
            if damage > 0:
                reward += self.reward_on_hit

        # Check for good blocks
        if events and "blocked_damage" in events:
            blocked = events["blocked_damage"]
            if blocked >= 3:  # Threshold for good block
                reward += self.reward_good_block

        # Check for overpitching
        if events and "pitch_sum" in events and "card_cost" in events:
            pitch_sum = events["pitch_sum"]
            card_cost = events["card_cost"]
            if pitch_sum > card_cost:
                reward += self.reward_overpitch

        if done:
            actor_life = next_state.players[actor].life
            opponent_life = next_state.players[opponent].life
            if actor_life > 0 and opponent_life <= 0:
                reward = self.reward_win
            elif opponent_life > 0 and actor_life <= 0:
                reward = self.reward_loss
            else:
                reward = self.reward_draw

        obs = encode_observation(self.state, config=self.encoder_config)

        # NEW: Check if episode should be truncated due to max steps
        truncated = self._step_count >= self.max_episode_steps
        if truncated and not done:
            # Game ran too long without natural termination
            # Give small negative reward to discourage infinite games
            reward += -0.5

        next_actions = self.legal_actions() if not (done or truncated) else []
        info = {
            "legal_actions": next_actions,
            "legal_action_mask": legal_action_mask(next_actions, self.action_vocab) if not (done or truncated) else np.zeros(
                len(self.action_vocab), dtype=np.bool_
            ),
            "actor": current_actor_index(self.state) if not (done or truncated) else None,
            "prev_actor": actor,
            "rules_version": self.rules_version,
            "events": events,
            "step_count": self._step_count,
            "seed": self._seed,
            "truncated": truncated,  # NEW: Add truncation info
        }
        # Gymnasium returns 5-tuple: (obs, reward, terminated, truncated, info)
        # Add action mask to observation for SB3 action masking
        obs_with_mask = obs.copy()
        obs_with_mask["legal_action_mask"] = info["legal_action_mask"]
        return obs_with_mask, float(reward), done, truncated, info

    def clone(self) -> GameState:
        return self.state.copy()

    def get_env_state(self) -> FabgameEnvState:
        return FabgameEnvState(
            state=self.state.copy(),
            seed=self._seed,
            rules_version=self.rules_version,
            step_count=self._step_count,
        )

    def restore(self, env_state: FabgameEnvState) -> None:
        self._state = env_state.state.copy()
        self._seed = env_state.seed
        self.rules_version = env_state.rules_version
        self._step_count = env_state.step_count
        self._done = False

    def serialize(self) -> Dict[str, Any]:
        return {
            "seed": self._seed,
            "rules_version": self.rules_version,
            "step_count": self._step_count,
        }

    def render(self, mode: str = "human") -> Optional[str]:
        """Gymnasium render method - not implemented for now."""
        return None

    def close(self) -> None:
        """Gymnasium close method."""
        pass


__all__ = ["FabgameEnv", "FabgameEnvState"]
