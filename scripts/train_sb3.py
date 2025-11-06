#!/usr/bin/env python
"""
Stable Baselines 3 training script for fabgame.

Usage:
    python -m scripts.train_sb3 --episodes 100 --checkpoint-dir checkpoints/
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

try:  # pragma: no cover - dependency guard
    import numpy as np
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("scripts/train_sb3.py requires numpy to be installed") from exc

try:  # pragma: no cover - optional dependency
    import gymnasium as gym
    from gymnasium import spaces
    from stable_baselines3 import PPO
    from stable_baselines3.common.callbacks import EvalCallback
    from stable_baselines3.common.monitor import Monitor
    from stable_baselines3.common.policies import ActorCriticPolicy
    from sb3_contrib.common.wrappers import ActionMasker
    import torch
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("scripts/train_sb3.py requires gymnasium, stable-baselines3, and sb3-contrib to be installed") from exc

from fabgame.rl.env import FabgameEnv


class MaskableActorCriticPolicy(ActorCriticPolicy):
    """Custom policy that supports action masking."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def forward(self, obs, deterministic=False):
        # Get base features
        features = self.extract_features(obs)
        latent_pi, latent_vf = self.mlp_extractor(features)
        logits = self.action_net(latent_pi)
        values = self.value_net(latent_vf)

        # Apply action mask if available in observation
        if isinstance(obs, dict) and "legal_action_mask" in obs:
            mask = obs["legal_action_mask"]
            # Convert mask to tensor and apply log masking
            mask_tensor = torch.from_numpy(mask.astype(np.float32)).to(logits.device)
            logits = logits + torch.log(mask_tensor.clamp(min=1e-8))

        # Sample action
        if deterministic:
            actions = torch.argmax(logits, dim=1)
        else:
            probs = torch.softmax(logits, dim=1)
            actions = torch.multinomial(probs, 1).squeeze(-1)

        return actions, values, logits


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train PPO using Stable Baselines 3.")
    parser.add_argument("--total-timesteps", type=int, default=100000, help="Total training timesteps.")
    parser.add_argument("--learning-rate", type=float, default=3e-4, help="Learning rate.")
    parser.add_argument("--n-steps", type=int, default=2048, help="Number of steps per rollout.")
    parser.add_argument("--batch-size", type=int, default=64, help="Minibatch size.")
    parser.add_argument("--n-epochs", type=int, default=10, help="Number of epochs per update.")
    parser.add_argument("--gamma", type=float, default=0.99, help="Discount factor.")
    parser.add_argument("--gae-lambda", type=float, default=0.95, help="GAE lambda.")
    parser.add_argument("--clip-range", type=float, default=0.2, help="PPO clip range.")
    parser.add_argument("--ent-coef", type=float, default=0.0, help="Entropy coefficient.")
    parser.add_argument("--vf-coef", type=float, default=0.5, help="Value function coefficient.")
    parser.add_argument("--max-grad-norm", type=float, default=1.0, help="Max gradient norm.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    parser.add_argument("--eval-freq", type=int, default=10000, help="Evaluate every N timesteps.")
    parser.add_argument("--eval-episodes", type=int, default=10, help="Number of evaluation episodes.")
    parser.add_argument(
        "--checkpoint-dir",
        type=str,
        default="checkpoints_sb3",
        help="Directory for saving policy checkpoints.",
    )
    parser.add_argument("--device", type=str, default="auto", help="Torch device (auto, cpu, cuda).")
    parser.add_argument("--rules-version", type=str, default="standard", help="Rules version label.")
    return parser.parse_args()


def make_env(rules_version: str, seed: int = 0, reward_step: float = 0.0, reward_on_hit: float = 0.0, reward_good_block: float = 0.0, reward_overpitch: float = 0.0):
    """Create a monitored environment."""
    def _init():
        env = FabgameEnv(
            rules_version=rules_version,
            reward_step=reward_step,
            reward_on_hit=reward_on_hit,
            reward_good_block=reward_good_block,
            reward_overpitch=reward_overpitch,
        )
        # Add action mask to observation for proper masking
        env = ActionMasker(env, action_mask_fn=lambda env: env.action_masks())
        env = Monitor(env)
        return env
    return _init


def main() -> None:
    args = _parse_args()

    # Set random seeds
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    # Create environments
    env = make_env(
        args.rules_version,
        args.seed,
        reward_step=-0.01,
        reward_on_hit=0.2,
        reward_good_block=0,
        reward_overpitch=0,
    )()

    # Create eval env with action masking (don't double-wrap with Monitor)
    def make_eval_env():
        eval_env = FabgameEnv(rules_version=args.rules_version)
        eval_env = ActionMasker(eval_env, action_mask_fn=lambda env: env.action_masks())
        eval_env = Monitor(eval_env)
        return eval_env

    eval_env = make_eval_env()

    # Create checkpoint directory
    checkpoint_dir = Path(args.checkpoint_dir)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    # Disable evaluation callback for now to avoid masking issues
    eval_callback = None

    # Use Maskable PPO from sb3-contrib for proper action masking
    from sb3_contrib import MaskablePPO
    from sb3_contrib.ppo_mask import MultiInputPolicy

    model = MaskablePPO(
        MultiInputPolicy,
        env,
        learning_rate=args.learning_rate,
        n_steps=args.n_steps,
        batch_size=args.batch_size,
        n_epochs=args.n_epochs,
        gamma=args.gamma,
        gae_lambda=args.gae_lambda,
        clip_range=args.clip_range,
        ent_coef=args.ent_coef,
        vf_coef=args.vf_coef,
        max_grad_norm=args.max_grad_norm,
        device=args.device,
        verbose=1,
        seed=args.seed,
    )

    # Train the model
    print(f"Starting training for {args.total_timesteps} timesteps...")
    model.learn(
        total_timesteps=args.total_timesteps,
        callback=eval_callback,
    )

    # Save final model
    final_path = checkpoint_dir / "final_model"
    model.save(str(final_path))
    print(f"Training completed. Final model saved to {final_path}")


if __name__ == "__main__":
    main()