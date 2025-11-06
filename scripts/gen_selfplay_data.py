#!/usr/bin/env python
"""
Self-play data generator for fabgame.

Usage:
    python -m scripts.gen_selfplay_data --games 50 --output data/selfplay_50.npz
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:  # pragma: no cover - dependency guard
    import numpy as np
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("scripts/gen_selfplay_data.py requires numpy to be installed") from exc

from fabgame import deck as deck_lib
from fabgame.agents import bot_choose_action
from fabgame.models import ActType
from fabgame.rl import ACTION_VOCAB, FabgameEnv, legal_action_mask


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate heuristic self-play data for imitation learning.")
    parser.add_argument("--games", type=int, default=10, help="Number of self-play games to simulate.")
    parser.add_argument("--seed", type=int, default=1, help="Random seed controlling decks and turn order.")
    parser.add_argument(
        "--deck-pool",
        type=str,
        default=None,
        help="Optional directory containing deck JSON files. Random decks are used if omitted.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/selfplay_dataset.npz",
        help="Destination NPZ file to store trajectory data.",
    )
    parser.add_argument(
        "--max-pass-streak",
        type=int,
        default=6,
        help="Discard episodes that exceed this many consecutive PASS actions.",
    )
    parser.add_argument(
        "--max-no-damage",
        type=int,
        default=12,
        help="Discard episodes with this many consecutive steps without life loss.",
    )
    parser.add_argument(
        "--rules-version",
        type=str,
        default="standard",
        help="Rules version label stored alongside each transition.",
    )
    return parser.parse_args()


def _load_deck_pool(directory: Optional[str]) -> List[str]:
    if not directory:
        return []
    path = Path(directory)
    if not path.is_dir():
        raise FileNotFoundError(f"Deck pool directory not found: {directory}")
    return [str(p) for p in sorted(path.glob("*.json"))]


def _load_deck(path: str) -> Tuple[List, Dict[str, Any]]:
    cards, meta = deck_lib.load_deck_from_json(path)
    return cards, meta


def _deck_identifier(meta: Dict[str, Any], path: Optional[str]) -> str:
    name = meta.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    if path:
        return Path(path).stem
    return "random"


def _as_lists(obs: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
    """Convert observation values to numpy arrays, excluding metadata keys."""
    return {
        key: np.asarray(value, dtype=np.float32)
        for key, value in obs.items()
        if key not in {"legal_action_mask"}  # Exclude keys that aren't true observations
    }


class EpisodeDataBuffer:
    """Accumulates trajectory data across multiple episodes."""

    def __init__(self) -> None:
        self.obs_buffers: Dict[str, List[np.ndarray]] = {}
        self.legal_masks: List[np.ndarray] = []
        self.legal_action_indices: List[Sequence[int]] = []
        self.chosen_actions: List[int] = []
        self.rewards: List[float] = []
        self.dones: List[int] = []
        self.actors: List[int] = []
        self.rules_versions: List[str] = []
        self.deck_ids: List[Tuple[str, str]] = []
        self.episode_ids: List[int] = []

    def append_step(
        self,
        obs: Dict[str, np.ndarray],
        legal_mask: np.ndarray,
        action_indices: List[int],
        chosen_idx: int,
        actor: int,
        rules_version: str,
        deck_pair_id: Tuple[str, str],
        episode_id: int,
    ) -> None:
        """Append a single step to the buffer."""
        # Initialize buffers on first call, but only for keys already seen
        if not self.obs_buffers:
            for key in obs:
                self.obs_buffers[key] = []

        # Append observations, creating new buffers for new keys if needed
        for key, value in obs.items():
            if key not in self.obs_buffers:
                self.obs_buffers[key] = []
            self.obs_buffers[key].append(value.copy())

        self.legal_masks.append(legal_mask.astype(np.int8))
        self.legal_action_indices.append(action_indices)
        self.chosen_actions.append(chosen_idx)
        self.actors.append(actor)
        self.rules_versions.append(rules_version)
        self.deck_ids.append(deck_pair_id)
        self.episode_ids.append(episode_id)

    def append_outcome(self, reward: float, done: bool) -> None:
        """Append reward and done flag for the last step."""
        self.rewards.append(reward)
        self.dones.append(1 if done else 0)

    def rollback_episode(self, step_count: int) -> None:
        """Remove the last step_count steps from all buffers."""
        if step_count == 0:
            return

        for key in self.obs_buffers:
            self.obs_buffers[key] = self.obs_buffers[key][:-step_count]
        self.legal_masks[:] = self.legal_masks[:-step_count]
        self.legal_action_indices[:] = self.legal_action_indices[:-step_count]
        self.chosen_actions[:] = self.chosen_actions[:-step_count]
        self.rewards[:] = self.rewards[:-step_count]
        self.dones[:] = self.dones[:-step_count]
        self.actors[:] = self.actors[:-step_count]
        self.rules_versions[:] = self.rules_versions[:-step_count]
        self.deck_ids[:] = self.deck_ids[:-step_count]
        self.episode_ids[:] = self.episode_ids[:-step_count]

    def is_empty(self) -> bool:
        """Check if no data has been collected."""
        return len(self.legal_masks) == 0


class EpisodeStats:
    """Tracks statistics during episode simulation."""

    def __init__(self) -> None:
        self.pass_streak = 0
        self.max_pass_streak = 0
        self.steps_no_damage = 0
        self.max_no_damage = 0
        self.step_count = 0

    def record_action(self, action_type: ActType) -> None:
        """Record an action and update pass streak."""
        if action_type == ActType.PASS:
            self.pass_streak += 1
        else:
            self.pass_streak = 0
        self.max_pass_streak = max(self.max_pass_streak, self.pass_streak)

    def record_damage(self, prev_life: List[int], new_life: List[int]) -> None:
        """Record whether damage occurred and update no-damage streak."""
        if new_life == prev_life:
            self.steps_no_damage += 1
        else:
            self.steps_no_damage = 0
        self.max_no_damage = max(self.max_no_damage, self.steps_no_damage)

    def record_step(self) -> None:
        """Increment step counter."""
        self.step_count += 1

    def is_valid(self, max_pass_streak: int, max_no_damage: int) -> bool:
        """Check if episode meets validation criteria."""
        return self.max_pass_streak <= max_pass_streak and self.max_no_damage <= max_no_damage


def _load_deck_configuration(
    deck_pool: List[str], rng: random.Random
) -> Tuple[Optional[List], Optional[List], Optional[str], Optional[str], Optional[str], Optional[str], Tuple[str, str]]:
    """Load deck configuration for both players."""
    if not deck_pool:
        return None, None, None, None, None, None, ("random", "random")

    deck0_path = rng.choice(deck_pool)
    deck1_path = rng.choice(deck_pool)
    deck0, meta0 = _load_deck(deck0_path)
    deck1, meta1 = _load_deck(deck1_path)

    hero0 = meta0.get("hero")
    hero1 = meta1.get("hero")
    arena0 = meta0.get("arena")
    arena1 = meta1.get("arena")
    deck_pair_id = (_deck_identifier(meta0, deck0_path), _deck_identifier(meta1, deck1_path))

    return deck0, deck1, hero0, hero1, arena0, arena1, deck_pair_id


def _simulate_episode(
    env: FabgameEnv,
    initial_obs: Dict[str, np.ndarray],
    initial_info: Dict[str, Any],
    bot_rng: random.Random,
    deck_pair_id: Tuple[str, str],
    buffer: EpisodeDataBuffer,
    episode_id: int,
) -> EpisodeStats:
    """Simulate a single episode and collect trajectory data."""
    stats = EpisodeStats()
    obs = _as_lists(initial_obs)
    legal_actions = initial_info["legal_actions"]
    actor = initial_info["actor"]

    done = False
    max_steps = 1000  # Failsafe to prevent infinite loops

    while not done and legal_actions and stats.step_count < max_steps:
        chosen = bot_choose_action(env.state, bot_rng)
        chosen_idx = ACTION_VOCAB.index_for(chosen)
        mask = legal_action_mask(legal_actions, ACTION_VOCAB)
        action_indices = [ACTION_VOCAB.index_for(act) for act in legal_actions]

        buffer.append_step(
            obs=obs,
            legal_mask=mask,
            action_indices=action_indices,
            chosen_idx=chosen_idx,
            actor=actor,
            rules_version=env.rules_version,
            deck_pair_id=deck_pair_id,
            episode_id=episode_id,
        )

        prev_life = [player.life for player in env.state.players]

        try:
            next_obs, reward, terminated, truncated, next_info = env.step(chosen)
        except IndexError:
            # Episode failed due to error - increment step count before returning
            stats.record_step()
            return stats  # Stats will be invalid

        done = terminated or truncated
        buffer.append_outcome(reward, done)

        new_life = [player.life for player in env.state.players]
        stats.record_damage(prev_life, new_life)
        stats.record_action(chosen.typ)
        stats.record_step()

        obs = _as_lists(next_obs)
        legal_actions = next_info.get("legal_actions", [])
        legal_mask = next_info.get("legal_action_mask")
        actor = next_info.get("actor")

    return stats


def _build_dataset(buffer: EpisodeDataBuffer, args: argparse.Namespace, accepted_episodes: int, deck_pool: List[str]) -> Dict[str, np.ndarray]:
    """Construct final dataset dictionary from collected data."""
    dataset: Dict[str, np.ndarray] = {}

    for key, values in buffer.obs_buffers.items():
        dataset[f"obs__{key}"] = np.stack(values, axis=0)

    dataset["legal_action_mask"] = np.stack(buffer.legal_masks, axis=0)
    dataset["legal_actions"] = np.array(
        [np.array(entry, dtype=np.int32) for entry in buffer.legal_action_indices],
        dtype=object
    )
    dataset["chosen_action"] = np.array(buffer.chosen_actions, dtype=np.int32)
    dataset["reward"] = np.array(buffer.rewards, dtype=np.float32)
    dataset["done"] = np.array(buffer.dones, dtype=np.int8)
    dataset["actor"] = np.array(buffer.actors, dtype=np.int8)
    dataset["rules_version"] = np.array(buffer.rules_versions)
    dataset["deck_ids"] = np.array(buffer.deck_ids, dtype=object)
    dataset["episode_id"] = np.array(buffer.episode_ids, dtype=np.int32)

    metadata = {
        "games_requested": args.games,
        "episodes_kept": accepted_episodes,
        "max_pass_streak_filter": args.max_pass_streak,
        "max_no_damage_filter": args.max_no_damage,
        "rules_version": args.rules_version,
        "deck_pool": deck_pool,
    }
    dataset["metadata_json"] = np.array([json.dumps(metadata)], dtype=object)

    return dataset


def generate_dataset(args: argparse.Namespace) -> Dict[str, np.ndarray]:
    """Generate self-play dataset by simulating multiple episodes."""
    rng = random.Random(args.seed)
    deck_pool = _load_deck_pool(args.deck_pool)
    env = FabgameEnv(rules_version=args.rules_version)
    buffer = EpisodeDataBuffer()
    accepted_episodes = 0

    for game_idx in range(args.games):
        # Load deck configuration for this episode
        deck0, deck1, hero0, hero1, arena0, arena1, deck_pair_id = _load_deck_configuration(deck_pool, rng)

        # Reset environment with loaded decks
        obs, info = env.reset(
            seed=rng.randrange(1, 1 << 30),
            deck0=deck0,
            deck1=deck1,
            hero0=hero0,
            hero1=hero1,
            arena0=arena0,
            arena1=arena1,
        )

        # Simulate episode and collect statistics
        bot_rng = random.Random(rng.randrange(1, 1 << 30))
        stats = _simulate_episode(env, obs, info, bot_rng, deck_pair_id, buffer, accepted_episodes)

        # Validate episode and rollback if invalid
        if not stats.is_valid(args.max_pass_streak, args.max_no_damage):
            buffer.rollback_episode(stats.step_count)
            continue

        accepted_episodes += 1

    if buffer.is_empty():
        raise RuntimeError("No valid episodes generated; try relaxing filtering thresholds.")

    return _build_dataset(buffer, args, accepted_episodes, deck_pool)


def main() -> None:
    args = _parse_args()
    dataset = generate_dataset(args)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output_path, **dataset)
    print(f"Wrote dataset with {dataset['chosen_action'].shape[0]} transitions to {output_path}")


if __name__ == "__main__":
    main()
