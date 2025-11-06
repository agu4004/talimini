#!/usr/bin/env python
"""
Baseline PPO-style training loop for fabgame.

Usage:
    python -m scripts.train_rl --episodes 100 --checkpoint-dir checkpoints/
"""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

try:  # pragma: no cover - dependency guard
    import numpy as np
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("scripts/train_rl.py requires numpy to be installed") from exc

try:  # pragma: no cover - optional dependency
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.distributions import Categorical
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("scripts/train_rl.py requires PyTorch to be installed") from exc

from fabgame.agents import bot_choose_action
from fabgame.rl import ACTION_VOCAB, FabgameEnv


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a PPO-style policy against heuristic opponents.")
    parser.add_argument("--episodes", type=int, default=200, help="Number of training episodes.")
    parser.add_argument("--gamma", type=float, default=0.99, help="Discount factor.")
    parser.add_argument("--lr", type=float, default=3e-4, help="Learning rate.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    parser.add_argument(
        "--eval-interval",
        type=int,
        default=25,
        help="Evaluate the policy against heuristic bot every N episodes.",
    )
    parser.add_argument("--eval-games", type=int, default=10, help="Number of evaluation games per cycle.")
    parser.add_argument(
        "--checkpoint-dir",
        type=str,
        default="checkpoints",
        help="Directory for saving policy checkpoints.",
    )
    parser.add_argument(
        "--checkpoint-interval",
        type=int,
        default=50,
        help="Save a checkpoint every N episodes.",
    )
    parser.add_argument("--rules-version", type=str, default="standard", help="Rules version label.")
    parser.add_argument("--device", type=str, default="cpu", help="Torch device (cpu or cuda).")
    return parser.parse_args()


def flatten_observation(obs: Dict[str, np.ndarray]) -> torch.Tensor:
    buffers: List[torch.Tensor] = []
    for key in sorted(obs.keys()):
        value = obs[key]
        tensor = torch.from_numpy(np.asarray(value, dtype=np.float32)).reshape(-1)
        buffers.append(tensor)
    return torch.cat(buffers, dim=0)


class PolicyNetwork(nn.Module):
    def __init__(self, obs_dim: int, action_dim: int, hidden: int = 256) -> None:
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(obs_dim, hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden),
            nn.ReLU(),
        )
        self.policy_head = nn.Linear(hidden, action_dim)
        self.value_head = nn.Linear(hidden, 1)

    def forward(self, obs: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        hidden = self.encoder(obs)
        logits = self.policy_head(hidden)
        value = self.value_head(hidden)
        return logits, value.squeeze(-1)


def masked_logits(logits: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    safe_mask = mask.float()
    clipped = safe_mask.clamp(min=1e-6)
    return logits + torch.log(clipped)


@dataclass
class Transition:
    obs: torch.Tensor
    action_idx: int
    reward: float
    log_prob: torch.Tensor
    value: torch.Tensor
    mask: torch.Tensor
    done: bool


class Trainer:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.device = torch.device(args.device)
        self.env = FabgameEnv(rules_version=args.rules_version)
        sample_obs, _ = self.env.reset(seed=args.seed)
        obs_tensor = flatten_observation(sample_obs).to(self.device)
        self.obs_dim = obs_tensor.numel()
        self.action_dim = len(ACTION_VOCAB)
        self.policy = PolicyNetwork(self.obs_dim, self.action_dim).to(self.device)
        self.optimizer = optim.Adam(self.policy.parameters(), lr=args.lr)
        self.rng = random.Random(args.seed)
        self.global_step = 0
        self.checkpoint_dir = Path(args.checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def select_action(self, obs_tensor: torch.Tensor, mask: np.ndarray) -> Tuple[int, torch.Tensor, torch.Tensor]:
        obs_tensor = obs_tensor.to(self.device)
        logits, value = self.policy(obs_tensor.unsqueeze(0))
        mask_tensor = torch.from_numpy(mask.astype(np.float32)).to(self.device)
        masked = masked_logits(logits.squeeze(0), mask_tensor)
        distribution = Categorical(logits=masked)
        action_idx = distribution.sample()
        return int(action_idx.item()), distribution.log_prob(action_idx), value.squeeze(0)

    def compute_returns(self, rewards: List[float]) -> torch.Tensor:
        returns: List[float] = []
        running = 0.0
        for reward in reversed(rewards):
            running = reward + self.args.gamma * running
            returns.append(running)
        returns.reverse()
        return torch.tensor(returns, dtype=torch.float32, device=self.device)

    def rollout_episode(self) -> List[Transition]:
        obs, info = self.env.reset(seed=self.rng.randrange(1, 1 << 30))
        transitions: List[Transition] = []

        done = False
        while not done:
            mask = info["legal_action_mask"]
            if not mask.any():
                raise RuntimeError("Encountered state with no legal actions.")
            obs_tensor = flatten_observation(obs)
            action_idx, log_prob, value = self.select_action(obs_tensor, mask)
            action = ACTION_VOCAB.action_for_index(action_idx)
            next_obs, reward, done, next_info = self.env.step(action)
            transitions.append(
                Transition(
                    obs=obs_tensor,
                    action_idx=action_idx,
                    reward=reward,
                    log_prob=log_prob,
                    value=value,
                    mask=torch.from_numpy(mask.astype(np.float32)),
                    done=done,
                )
            )
            obs = next_obs
            info = next_info
            self.global_step += 1
        return transitions

    def optimize(self, transitions: List[Transition]) -> Tuple[float, float]:
        rewards = [t.reward for t in transitions]
        returns = self.compute_returns(rewards)
        log_probs = torch.stack([t.log_prob for t in transitions])
        values = torch.stack([t.value for t in transitions])
        advantages = returns - values.detach()

        policy_loss = -(log_probs * advantages).mean()
        value_loss = nn.functional.mse_loss(values, returns)
        loss = policy_loss + 0.5 * value_loss

        self.optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.policy.parameters(), max_norm=1.0)
        self.optimizer.step()
        return float(policy_loss.item()), float(value_loss.item())

    def evaluate(self, episodes: int) -> Dict[str, float]:
        wins = 0
        total_turns = 0
        evaluation_env = FabgameEnv(rules_version=self.args.rules_version)
        for _ in range(episodes):
            obs, info = evaluation_env.reset(seed=self.rng.randrange(1, 1 << 30))
            done = False
            turns = 0
            while not done:
                actor = info["actor"]
                if actor == 0:
                    mask = info["legal_action_mask"]
                    obs_tensor = flatten_observation(obs).to(self.device)
                    logits, _ = self.policy(obs_tensor.unsqueeze(0))
                    mask_tensor = torch.from_numpy(mask.astype(np.float32)).to(self.device)
                    masked = masked_logits(logits.squeeze(0), mask_tensor)
                    action_idx = masked.argmax().item()
                    action = ACTION_VOCAB.action_for_index(action_idx)
                else:
                    action = bot_choose_action(evaluation_env.state)
                obs, _, done, info = evaluation_env.step(action)
                turns += 1
            total_turns += turns
            player_life = evaluation_env.state.players[0].life
            opponent_life = evaluation_env.state.players[1].life
            if player_life > opponent_life:
                wins += 1
        return {
            "win_rate": wins / max(episodes, 1),
            "avg_turns": total_turns / max(episodes, 1),
        }

    def save_checkpoint(self, episode: int) -> None:
        path = self.checkpoint_dir / f"policy_ep{episode}.pt"
        torch.save(
            {
                "episode": episode,
                "model_state": self.policy.state_dict(),
                "optimizer_state": self.optimizer.state_dict(),
                "obs_dim": self.obs_dim,
                "action_dim": self.action_dim,
                "rules_version": self.args.rules_version,
            },
            path,
        )
        print(f"[checkpoint] Saved {path}")

    def train(self) -> None:
        for episode in range(1, self.args.episodes + 1):
            transitions = self.rollout_episode()
            policy_loss, value_loss = self.optimize(transitions)
            if episode % 10 == 0 or episode == 1:
                print(
                    f"[train] episode={episode} steps={len(transitions)} policy_loss={policy_loss:.4f} value_loss={value_loss:.4f}"
                )
            if episode % self.args.eval_interval == 0:
                stats = self.evaluate(self.args.eval_games)
                print(
                    f"[eval] episode={episode} win_rate={stats['win_rate']:.3f} avg_turns={stats['avg_turns']:.2f}"
                )
            if episode % self.args.checkpoint_interval == 0:
                self.save_checkpoint(episode)


def main() -> None:
    args = _parse_args()
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    random.seed(args.seed)
    trainer = Trainer(args)
    trainer.train()


if __name__ == "__main__":
    main()
