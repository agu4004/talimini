#!/usr/bin/env python
"""
Improved Stable Baselines 3 training script with better reward shaping and hyperparameters.

Key improvements over train_sb3.py:
- Better reward shaping (damage, blocking, resource efficiency)
- Entropy coefficient for exploration
- Larger batch sizes
- More training steps
- Annealing schedules for learning rate and entropy

Usage:
    python -m scripts.train_sb3_improved --total-timesteps 1000000
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Callable

try:  # pragma: no cover - dependency guard
    import numpy as np
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("scripts/train_sb3_improved.py requires numpy to be installed") from exc

try:  # pragma: no cover - optional dependency
    import gymnasium as gym
    from gymnasium import spaces
    from stable_baselines3.common.callbacks import EvalCallback, CheckpointCallback, CallbackList
    from stable_baselines3.common.monitor import Monitor
    from stable_baselines3.common.vec_env import DummyVecEnv
    from sb3_contrib.common.wrappers import ActionMasker
    import torch
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("scripts/train_sb3_improved.py requires gymnasium, stable-baselines3, and sb3-contrib to be installed") from exc

from fabgame.rl.env import FabgameEnv


def linear_schedule(initial_value: float, final_value: float = 0.0) -> Callable[[float], float]:
    """
    Linear learning rate schedule.

    Args:
        initial_value: Initial value
        final_value: Final value (default: 0.0)

    Returns:
        Schedule function that takes progress (0-1) and returns interpolated value
    """
    def func(progress_remaining: float) -> float:
        """
        Progress will decrease from 1 (beginning) to 0 (end).
        """
        return final_value + progress_remaining * (initial_value - final_value)
    return func


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train PPO using Stable Baselines 3 with improved hyperparameters.")

    # Training parameters
    parser.add_argument("--total-timesteps", type=int, default=1000000, help="Total training timesteps (default: 1M).")
    parser.add_argument("--learning-rate", type=float, default=3e-4, help="Initial learning rate.")
    parser.add_argument("--lr-final", type=float, default=1e-5, help="Final learning rate (for annealing).")
    parser.add_argument("--use-lr-annealing", action="store_true", help="Use learning rate annealing.")

    # PPO hyperparameters
    parser.add_argument("--n-steps", type=int, default=4096, help="Number of steps per rollout (increased from 2048).")
    parser.add_argument("--batch-size", type=int, default=256, help="Minibatch size (increased from 64).")
    parser.add_argument("--n-epochs", type=int, default=10, help="Number of epochs per update.")
    parser.add_argument("--gamma", type=float, default=0.99, help="Discount factor.")
    parser.add_argument("--gae-lambda", type=float, default=0.95, help="GAE lambda.")
    parser.add_argument("--clip-range", type=float, default=0.2, help="PPO clip range.")

    # Exploration parameters
    parser.add_argument("--ent-coef", type=float, default=0.01, help="Entropy coefficient (NEW: default 0.01 for exploration).")
    parser.add_argument("--ent-coef-final", type=float, default=0.001, help="Final entropy coefficient (for annealing).")
    parser.add_argument("--use-ent-annealing", action="store_true", help="Use entropy coefficient annealing.")

    # Value function parameters
    parser.add_argument("--vf-coef", type=float, default=0.5, help="Value function coefficient.")
    parser.add_argument("--max-grad-norm", type=float, default=0.5, help="Max gradient norm (reduced from 1.0).")

    # Reward shaping parameters (IMPROVED DEFAULTS)
    parser.add_argument("--reward-win", type=float, default=1.0, help="Reward for winning.")
    parser.add_argument("--reward-loss", type=float, default=-1.0, help="Reward for losing.")
    parser.add_argument("--reward-step", type=float, default=-0.005, help="Step penalty (reduced from -0.01).")
    parser.add_argument("--reward-on-hit", type=float, default=0.5, help="Reward for dealing damage (increased from 0.2).")
    parser.add_argument("--reward-good-block", type=float, default=0.3, help="Reward for efficient blocking (NEW).")
    parser.add_argument("--reward-overpitch", type=float, default=-0.2, help="Penalty for overpitching (NEW).")

    # Environment parameters
    parser.add_argument("--max-episode-steps", type=int, default=500, help="Maximum steps per episode (NEW: prevents infinite games).")
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    parser.add_argument("--rules-version", type=str, default="standard", help="Rules version label.")

    # Checkpointing and evaluation
    parser.add_argument("--checkpoint-dir", type=str, default="checkpoints_sb3_improved", help="Directory for saving checkpoints.")
    parser.add_argument("--checkpoint-freq", type=int, default=50000, help="Save checkpoint every N timesteps.")
    parser.add_argument("--eval-freq", type=int, default=50000, help="Evaluate every N timesteps.")
    parser.add_argument("--eval-episodes", type=int, default=10, help="Number of evaluation episodes.")

    # Device
    parser.add_argument("--device", type=str, default="auto", help="Torch device (auto, cpu, cuda).")

    # Resume training
    parser.add_argument("--resume", type=str, default=None, help="Path to checkpoint to resume training from.")

    return parser.parse_args()


def make_env(
    rules_version: str,
    seed: int = 0,
    reward_win: float = 1.0,
    reward_loss: float = -1.0,
    reward_step: float = -0.005,
    reward_on_hit: float = 0.5,
    reward_good_block: float = 0.3,
    reward_overpitch: float = -0.2,
    max_episode_steps: int = 500,
):
    """Create a monitored environment with improved reward shaping."""
    def _init():
        env = FabgameEnv(
            rules_version=rules_version,
            reward_win=reward_win,
            reward_loss=reward_loss,
            reward_step=reward_step,
            reward_on_hit=reward_on_hit,
            reward_good_block=reward_good_block,
            reward_overpitch=reward_overpitch,
            max_episode_steps=max_episode_steps,
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

    # Create checkpoint directory
    checkpoint_dir = Path(args.checkpoint_dir)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    # Print configuration
    print("=" * 80)
    print("IMPROVED TRAINING CONFIGURATION (WITH FREEZE FIX)")
    print("=" * 80)
    print(f"Total timesteps: {args.total_timesteps:,}")
    print(f"Max episode steps: {args.max_episode_steps} (NEW: Prevents infinite games)")
    print(f"Batch size: {args.batch_size} (original: 64)")
    print(f"Rollout steps: {args.n_steps} (original: 2048)")
    print(f"Entropy coefficient: {args.ent_coef} → {args.ent_coef_final if args.use_ent_annealing else args.ent_coef} (original: 0.0)")
    print(f"Learning rate: {args.learning_rate} → {args.lr_final if args.use_lr_annealing else args.learning_rate}")
    print()
    print("REWARD SHAPING:")
    print(f"  Win/Loss: +{args.reward_win}/{args.reward_loss}")
    print(f"  Step penalty: {args.reward_step} (original: -0.01)")
    print(f"  On-hit reward: +{args.reward_on_hit} (original: 0.2)")
    print(f"  Good block reward: +{args.reward_good_block} (NEW)")
    print(f"  Overpitch penalty: {args.reward_overpitch} (NEW)")
    print("=" * 80)
    print()

    # Create training environment
    env = make_env(
        args.rules_version,
        args.seed,
        reward_win=args.reward_win,
        reward_loss=args.reward_loss,
        reward_step=args.reward_step,
        reward_on_hit=args.reward_on_hit,
        reward_good_block=args.reward_good_block,
        reward_overpitch=args.reward_overpitch,
        max_episode_steps=args.max_episode_steps,
    )()

    # Create evaluation environment
    eval_env = make_env(
        args.rules_version,
        args.seed + 1000,  # Different seed for eval
        reward_win=args.reward_win,
        reward_loss=args.reward_loss,
        reward_step=args.reward_step,
        reward_on_hit=args.reward_on_hit,
        reward_good_block=args.reward_good_block,
        reward_overpitch=args.reward_overpitch,
        max_episode_steps=args.max_episode_steps,
    )()

    # Setup learning rate schedule
    if args.use_lr_annealing:
        learning_rate = linear_schedule(args.learning_rate, args.lr_final)
        print(f"Using learning rate annealing: {args.learning_rate} → {args.lr_final}")
    else:
        learning_rate = args.learning_rate

    # Setup entropy coefficient schedule
    if args.use_ent_annealing:
        ent_coef = linear_schedule(args.ent_coef, args.ent_coef_final)
        print(f"Using entropy annealing: {args.ent_coef} → {args.ent_coef_final}")
    else:
        ent_coef = args.ent_coef

    # Use Maskable PPO from sb3-contrib
    from sb3_contrib import MaskablePPO
    from sb3_contrib.ppo_mask import MultiInputPolicy

    # Create or load model
    if args.resume:
        print(f"Resuming training from: {args.resume}")
        model = MaskablePPO.load(
            args.resume,
            env=env,
            device=args.device,
        )
        # Update hyperparameters if resuming
        model.learning_rate = learning_rate
        model.ent_coef = ent_coef
        model.batch_size = args.batch_size
        model.n_steps = args.n_steps
    else:
        model = MaskablePPO(
            MultiInputPolicy,
            env,
            learning_rate=learning_rate,
            n_steps=args.n_steps,
            batch_size=args.batch_size,
            n_epochs=args.n_epochs,
            gamma=args.gamma,
            gae_lambda=args.gae_lambda,
            clip_range=args.clip_range,
            ent_coef=ent_coef,
            vf_coef=args.vf_coef,
            max_grad_norm=args.max_grad_norm,
            device=args.device,
            verbose=1,
            seed=args.seed,
        )

    # Setup callbacks
    callbacks = []

    # Checkpoint callback - save model periodically
    checkpoint_callback = CheckpointCallback(
        save_freq=args.checkpoint_freq,
        save_path=str(checkpoint_dir),
        name_prefix="ppo_fabgame",
        save_replay_buffer=False,
        save_vecnormalize=False,
    )
    callbacks.append(checkpoint_callback)

    # Evaluation callback - test against fixed scenarios
    eval_callback = EvalCallback(
        eval_env,
        best_model_save_path=str(checkpoint_dir / "best_model"),
        log_path=str(checkpoint_dir / "eval_logs"),
        eval_freq=args.eval_freq,
        n_eval_episodes=args.eval_episodes,
        deterministic=True,
        render=False,
    )
    callbacks.append(eval_callback)

    callback = CallbackList(callbacks)

    # Train the model
    print(f"\nStarting training for {args.total_timesteps:,} timesteps...")
    print(f"Expected games: ~{args.total_timesteps // 50:,} (assuming ~50 steps/game)")
    print(f"Checkpoints will be saved to: {checkpoint_dir}")
    print()

    model.learn(
        total_timesteps=args.total_timesteps,
        callback=callback,
        log_interval=10,
        progress_bar=True,
    )

    # Save final model
    final_path = checkpoint_dir / "final_model"
    model.save(str(final_path))
    print(f"\nTraining completed! Final model saved to {final_path}")
    print()
    print("=" * 80)
    print("NEXT STEPS:")
    print("=" * 80)
    print("1. Evaluate your model:")
    print(f"   python -m scripts.eval_agents --agents bot --agents ml:{final_path}.zip --games 100")
    print()
    print("2. Play against your model:")
    print(f"   python main.py hb --ml-policy {final_path}.zip")
    print()
    print("3. Compare with best checkpoint:")
    print(f"   ls {checkpoint_dir}/best_model/")
    print("=" * 80)


if __name__ == "__main__":
    main()
