from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence

try:  # pragma: no cover - dependency guard
    import numpy as np
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("fabgame.agents_ml requires numpy to be installed") from exc

try:  # pragma: no cover - optional dependency
    import torch
    import torch.nn as nn
    from torch.distributions import Categorical
except ImportError:  # pragma: no cover
    torch = None  # type: ignore
    nn = None  # type: ignore

try:  # pragma: no cover - optional dependency for SB3
    from stable_baselines3 import PPO
except ImportError:  # pragma: no cover
    PPO = None  # type: ignore


class SB3Policy:
    def __init__(self, model) -> None:
        self.model = model

    def select_action(self, obs: Dict[str, np.ndarray], mask: np.ndarray, deterministic: bool = True) -> int:
        # SB3 expects dict observation, not flattened
        action, _ = self.model.predict(obs, action_masks=mask, deterministic=deterministic)
        return int(action)

from .agents import bot_choose_action
from .engine import current_actor_index, enumerate_legal_actions
from .models import Action, GameState
from .rl import ACTION_VOCAB, EncoderConfig, encode_observation, legal_action_mask


def flatten_observation(obs: Dict[str, np.ndarray]) -> "torch.Tensor":
    if torch is None:  # pragma: no cover - guarded import
        raise RuntimeError("Torch is required for ML inference.")
    tensors = []
    for key in sorted(obs.keys()):
        value = np.asarray(obs[key], dtype=np.float32).reshape(-1)
        tensors.append(torch.from_numpy(value))
    return torch.cat(tensors, dim=0)


class PolicyNetwork(nn.Module):  # type: ignore[misc]
    def __init__(self, obs_dim: int, action_dim: int, hidden: int = 256) -> None:
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(obs_dim, hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden),
            nn.ReLU(),
        )
        self.policy_head = nn.Linear(hidden, action_dim)

    def forward(self, obs: "torch.Tensor") -> "torch.Tensor":
        hidden = self.encoder(obs)
        return self.policy_head(hidden)


@dataclass
class TorchPolicy:
    network: PolicyNetwork
    device: "torch.device"

    def select_action(self, obs: Dict[str, np.ndarray], mask: np.ndarray, deterministic: bool = True) -> int:
        if torch is None:
            raise RuntimeError("Torch is required for ML inference.")
        obs_tensor = flatten_observation(obs).to(self.device).unsqueeze(0)
        mask_tensor = torch.from_numpy(mask.astype(np.float32)).to(self.device)
        with torch.no_grad():
            logits = self.network(obs_tensor).squeeze(0)
            masked = logits + torch.log(mask_tensor.clamp(min=1e-6))
            if deterministic:
                return int(masked.argmax().item())
            distribution = Categorical(logits=masked)
            return int(distribution.sample().item())


def load_policy(path: str, device: str = "cpu") -> Optional[TorchPolicy]:
    if torch is None:
        return None
    checkpoint_path = Path(path)
    if not checkpoint_path.is_file():
        return None
    data = torch.load(checkpoint_path, map_location=device)
    obs_dim = int(data["obs_dim"])
    action_dim = int(data["action_dim"])
    network = PolicyNetwork(obs_dim, action_dim)
    network.load_state_dict(data["model_state"])
    network.eval()
    return TorchPolicy(network=network.to(device), device=torch.device(device))


def load_sb3_policy(path: str) -> Optional[SB3Policy]:
    try:
        from sb3_contrib import MaskablePPO
    except ImportError:
        return None
    checkpoint_path = Path(path)
    if not checkpoint_path.is_file():
        return None
    model = MaskablePPO.load(str(checkpoint_path))
    return SB3Policy(model)


def _default_policy_path() -> Optional[str]:
    env_path = os.environ.get("FABGAME_ML_POLICY")
    if env_path:
        return env_path
    default_path = Path("checkpoints/latest.pt")
    if default_path.is_file():
        return str(default_path)
    return None


def _default_sb3_policy_path() -> Optional[str]:
    env_path = os.environ.get("FABGAME_SB3_POLICY")
    if env_path:
        return env_path
    default_path = Path("checkpoints_sb3/final_model.zip")
    if default_path.is_file():
        return str(default_path)
    return None


def ml_bot_choose_action(
    gs: GameState,
    *,
    policy: Optional[TorchPolicy] = None,
    sb3_policy: Optional[SB3Policy] = None,
    legal_actions: Optional[Sequence[Action]] = None,
    deterministic: bool = True,
    timeout_seconds: float = 0.05,
    encoder_config: Optional[EncoderConfig] = None,
) -> Action:
    """
    Choose an action for the current actor using an ML policy with heuristic fallback.
    """

    legal = list(legal_actions) if legal_actions is not None else enumerate_legal_actions(gs)
    if not legal:
        return bot_choose_action(gs)

    mask = legal_action_mask(legal, ACTION_VOCAB)
    actor = current_actor_index(gs)
    encoder_config = encoder_config or EncoderConfig()
    obs = encode_observation(gs, acting_player=actor, config=encoder_config)

    if policy is None and sb3_policy is None:
        path = _default_policy_path()
        if path:
            policy = load_policy(path)
        if policy is None:
            sb3_path = _default_sb3_policy_path()
            if sb3_path:
                sb3_policy = load_sb3_policy(sb3_path)
    if policy is None and sb3_policy is None:
        return bot_choose_action(gs, random.Random())

    start = time.perf_counter()
    try:
        if policy is not None:
            action_idx = policy.select_action(obs, mask, deterministic=deterministic)
        else:
            action_idx = sb3_policy.select_action(obs, mask, deterministic=deterministic)
    except Exception:
        return bot_choose_action(gs, random.Random())
    elapsed = time.perf_counter() - start
    if elapsed > timeout_seconds:
        return bot_choose_action(gs, random.Random())

    try:
        chosen = ACTION_VOCAB.action_for_index(action_idx)
    except (IndexError, KeyError):
        return bot_choose_action(gs, random.Random())
    if chosen not in legal:
        return bot_choose_action(gs, random.Random())
    return chosen


__all__ = ["TorchPolicy", "SB3Policy", "load_policy", "load_sb3_policy", "ml_bot_choose_action"]
