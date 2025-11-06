#!/usr/bin/env python
"""
Debug script to test if the environment can complete games without freezing.
"""

import time
from fabgame.rl.env import FabgameEnv
from sb3_contrib.common.wrappers import ActionMasker

def test_environment_games(n_games=5, max_steps_per_game=500):
    """Test if environment can complete games without hanging."""

    print("Testing FabgameEnv for potential hangs/infinite loops...")
    print("=" * 60)

    for game_num in range(n_games):
        print(f"\nGame {game_num + 1}/{n_games}:")

        # Create environment
        env = FabgameEnv(
            rules_version="standard",
            reward_step=-0.005,
            reward_on_hit=0.5,
            reward_good_block=0.3,
            reward_overpitch=-0.2,
        )
        env = ActionMasker(env, action_mask_fn=lambda e: e.action_masks())

        # Reset
        obs, info = env.reset(seed=42 + game_num)
        done = False
        step_count = 0

        start_time = time.time()
        last_report_time = start_time

        while not done and step_count < max_steps_per_game:
            # Get action mask
            action_mask = env.action_masks()
            legal_actions = [i for i, mask in enumerate(action_mask) if mask]

            if not legal_actions:
                print(f"  WARNING: No legal actions at step {step_count}")
                break

            # Take random legal action
            import random
            action = random.choice(legal_actions)

            # Step
            obs, reward, terminated, truncated, info = env.step(action)
            done = terminated or truncated
            step_count += 1

            # Report progress every 5 seconds
            current_time = time.time()
            if current_time - last_report_time > 5.0:
                elapsed = current_time - start_time
                print(f"  Step {step_count}, elapsed: {elapsed:.1f}s")
                last_report_time = current_time

        elapsed = time.time() - start_time

        if done:
            print(f"  ✓ Game completed in {step_count} steps ({elapsed:.2f}s)")
        else:
            print(f"  ⚠ Game truncated at {step_count} steps ({elapsed:.2f}s)")

        env.close()

    print("\n" + "=" * 60)
    print("Environment test completed successfully!")
    print("If you saw any games taking >30 seconds, there may be performance issues.")

if __name__ == "__main__":
    test_environment_games(n_games=5, max_steps_per_game=500)
