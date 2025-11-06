#!/usr/bin/env python
"""
Quick evaluation script to test ML agent vs Heuristic bot.

Usage:
    # Test existing model
    python -m scripts.quick_eval --model checkpoints_sb3/final_model.zip --games 50

    # Test improved model
    python -m scripts.quick_eval --model checkpoints_sb3_improved/final_model.zip --games 100
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

try:
    import numpy as np
except ImportError as exc:
    raise RuntimeError("scripts/quick_eval.py requires numpy") from exc

from fabgame.agents.heuristic import HeuristicAgent
from fabgame.agents.ml import MLAgent
from fabgame.engine import apply_action, enumerate_legal_actions, new_game, current_actor_index


def evaluate_ml_vs_heuristic(ml_policy_path: str, n_games: int = 50, seed: int = 42) -> dict:
    """
    Evaluate ML agent against heuristic bot.

    Args:
        ml_policy_path: Path to trained ML model
        n_games: Number of games to play
        seed: Random seed

    Returns:
        Dictionary with evaluation statistics
    """
    print(f"Loading ML model from: {ml_policy_path}")
    ml_agent = MLAgent(
        policy_path=Path(ml_policy_path),
        name="ML Agent",
        use_fallback=True,
        deterministic=True,
    )

    heuristic_agent = HeuristicAgent(name="Heuristic Bot", seed=seed)

    # Statistics
    ml_wins = 0
    heuristic_wins = 0
    draws = 0
    ml_total_life = 0
    heuristic_total_life = 0
    total_turns = 0
    game_lengths = []
    ml_fallback_count = 0

    print(f"\nPlaying {n_games} games (ML vs Heuristic)...")
    print("=" * 60)

    for game_num in range(n_games):
        # Alternate who goes first
        ml_player_idx = game_num % 2
        heuristic_player_idx = 1 - ml_player_idx

        # Create new game
        game = new_game(seed=seed + game_num)
        state = game.state
        turns = 0
        max_turns = 200  # Prevent infinite games

        # Play game
        while state.winner is None and turns < max_turns:
            actor = current_actor_index(state)
            legal = list(enumerate_legal_actions(state))

            if not legal:
                break

            # Choose action
            if actor == ml_player_idx:
                try:
                    action = ml_agent.choose_action(state)
                except Exception as e:
                    print(f"  Game {game_num + 1}: ML agent error: {e}, using fallback")
                    ml_fallback_count += 1
                    action = heuristic_agent.choose_action(state)
            else:
                action = heuristic_agent.choose_action(state)

            # Apply action
            state, done, events = apply_action(state, action)
            turns += 1

            if done:
                break

        # Record results
        ml_life = state.players[ml_player_idx].life
        heuristic_life = state.players[heuristic_player_idx].life

        ml_total_life += ml_life
        heuristic_total_life += heuristic_life
        total_turns += turns
        game_lengths.append(turns)

        if ml_life > heuristic_life:
            ml_wins += 1
            winner = "ML"
        elif heuristic_life > ml_life:
            heuristic_wins += 1
            winner = "Heuristic"
        else:
            draws += 1
            winner = "Draw"

        # Print progress every 10 games
        if (game_num + 1) % 10 == 0 or game_num == n_games - 1:
            print(f"  Game {game_num + 1}/{n_games}: {winner} (ML: {ml_life} HP, Heuristic: {heuristic_life} HP, Turns: {turns})")

    print("=" * 60)
    print("\nRESULTS:")
    print("-" * 60)

    ml_win_rate = ml_wins / n_games * 100
    heuristic_win_rate = heuristic_wins / n_games * 100
    draw_rate = draws / n_games * 100

    print(f"ML Agent wins:       {ml_wins}/{n_games} ({ml_win_rate:.1f}%)")
    print(f"Heuristic Bot wins:  {heuristic_wins}/{n_games} ({heuristic_win_rate:.1f}%)")
    print(f"Draws:               {draws}/{n_games} ({draw_rate:.1f}%)")
    print()
    print(f"Average ML life:     {ml_total_life / n_games:.1f}")
    print(f"Average Heuristic life: {heuristic_total_life / n_games:.1f}")
    print(f"Average game length: {total_turns / n_games:.1f} turns")
    print(f"Min/Max game length: {min(game_lengths)}/{max(game_lengths)} turns")

    if ml_fallback_count > 0:
        print(f"\nML fallback count:   {ml_fallback_count} ({ml_fallback_count / n_games * 100:.1f}%)")

    print("-" * 60)

    # Performance assessment
    print("\nPERFORMANCE ASSESSMENT:")
    if ml_win_rate >= 55:
        print("🎉 EXCELLENT! ML agent exceeds target (>55% win rate)")
    elif ml_win_rate >= 50:
        print("✓ GOOD! ML agent matches heuristic (~50% win rate)")
    elif ml_win_rate >= 40:
        print("⚠ FAIR. ML agent is competitive but needs improvement")
    elif ml_win_rate >= 30:
        print("⚠ POOR. ML agent needs more training")
    else:
        print("❌ VERY POOR. Check training configuration")

    print()
    print("Target win rate: >55% (from ML_BOT_PLAN.md)")
    print("=" * 60)

    return {
        "ml_wins": ml_wins,
        "heuristic_wins": heuristic_wins,
        "draws": draws,
        "ml_win_rate": ml_win_rate,
        "heuristic_win_rate": heuristic_win_rate,
        "avg_ml_life": ml_total_life / n_games,
        "avg_heuristic_life": heuristic_total_life / n_games,
        "avg_turns": total_turns / n_games,
        "ml_fallback_count": ml_fallback_count,
    }


def main():
    parser = argparse.ArgumentParser(description="Quick evaluation of ML agent vs Heuristic bot")
    parser.add_argument("--model", type=str, required=True, help="Path to trained model (.zip file)")
    parser.add_argument("--games", type=int, default=50, help="Number of games to play (default: 50)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")

    args = parser.parse_args()

    # Check if model exists
    model_path = Path(args.model)
    if not model_path.exists():
        print(f"ERROR: Model not found at {args.model}")
        print("\nAvailable models:")
        for checkpoint_dir in ["checkpoints_sb3", "checkpoints_sb3_improved"]:
            if Path(checkpoint_dir).exists():
                print(f"\n{checkpoint_dir}/")
                for model_file in Path(checkpoint_dir).glob("*.zip"):
                    print(f"  - {model_file}")
        return

    start_time = time.time()
    results = evaluate_ml_vs_heuristic(args.model, args.games, args.seed)
    elapsed = time.time() - start_time

    print(f"\nEvaluation completed in {elapsed:.1f} seconds")
    print(f"Average time per game: {elapsed / args.games:.2f} seconds")


if __name__ == "__main__":
    main()
