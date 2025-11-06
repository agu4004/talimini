#!/usr/bin/env python
"""
Evaluation script for Stable Baselines 3 models in fabgame.

Usage:
    python -m scripts.eval_sb3 --model-path checkpoints_sb3/final_model --games 50
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:  # pragma: no cover - dependency guard
    import numpy as np
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("scripts/eval_sb3.py requires numpy to be installed") from exc

try:  # pragma: no cover - optional dependency
    from stable_baselines3 import PPO
    from stable_baselines3.common.monitor import Monitor
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("scripts/eval_sb3.py requires stable-baselines3 to be installed") from exc

from fabgame.agents import bot_choose_action
from fabgame.rl.env import FabgameEnv


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate SB3 model against heuristic bot.")
    parser.add_argument("--model-path", type=str, required=True, help="Path to SB3 model.")
    parser.add_argument("--games", type=int, default=50, help="Number of games to evaluate.")
    parser.add_argument("--seed", type=int, default=1234, help="Base random seed.")
    parser.add_argument("--rules-version", type=str, default="standard", help="Rules version.")
    parser.add_argument("--output", type=str, default=None, help="JSON output file for results.")
    parser.add_argument("--deterministic", action="store_true", help="Use deterministic actions.")
    return parser.parse_args()


def evaluate_model(args: argparse.Namespace) -> dict:
    """Evaluate the model against heuristic bot."""
    # Load model
    model_path = Path(args.model_path)
    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path}")

    model = PPO.load(str(model_path))

    # Create environment
    env = FabgameEnv(rules_version=args.rules_version)
    env = Monitor(env)

    wins = 0
    total_turns = 0
    total_rewards = []

    for game_idx in range(args.games):
        obs, info = env.reset(seed=args.seed + game_idx)
        done = False
        episode_reward = 0
        turns = 0

        while not done:
            actor = info["actor"]
            if actor == 0:  # Model's turn
                # Add action mask to observation for masking
                obs_with_mask = obs.copy()
                obs_with_mask["legal_action_mask"] = info["legal_action_mask"]

                action, _ = model.predict(obs_with_mask, deterministic=args.deterministic)
            else:  # Bot's turn
                action = bot_choose_action(env.unwrapped.state)

            obs, reward, terminated, truncated, info = env.step(action)
            done = terminated or truncated
            episode_reward += reward
            turns += 1

        total_turns += turns
        total_rewards.append(episode_reward)

        # Check winner
        final_life_0 = env.unwrapped.state.players[0].life
        final_life_1 = env.unwrapped.state.players[1].life
        if final_life_0 > final_life_1:
            wins += 1

    results = {
        "games_played": args.games,
        "wins": wins,
        "win_rate": wins / args.games,
        "avg_turns": total_turns / args.games,
        "avg_reward": np.mean(total_rewards),
        "std_reward": np.std(total_rewards),
        "model_path": str(model_path),
        "deterministic": args.deterministic,
        "rules_version": args.rules_version,
    }

    return results


def main() -> None:
    args = _parse_args()
    results = evaluate_model(args)

    print("Evaluation Results:")
    print(f"Games played: {results['games_played']}")
    print(f"Win rate: {results['win_rate']:.3f}")
    print(f"Average turns: {results['avg_turns']:.2f}")
    print(f"Average reward: {results['avg_reward']:.3f} ± {results['std_reward']:.3f}")

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"Results saved to {output_path}")


if __name__ == "__main__":
    main()