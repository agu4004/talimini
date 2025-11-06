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
    return {key: np.asarray(value, dtype=np.float32) for key, value in obs.items()}


def generate_dataset(args: argparse.Namespace) -> Dict[str, np.ndarray]:
    rng = random.Random(args.seed)
    deck_pool = _load_deck_pool(args.deck_pool)

    env = FabgameEnv(rules_version=args.rules_version)

    obs_buffers: Dict[str, List[np.ndarray]] = {}
    legal_masks: List[np.ndarray] = []
    legal_action_indices: List[Sequence[int]] = []
    chosen_actions: List[int] = []
    rewards: List[float] = []
    dones: List[int] = []
    actors: List[int] = []
    rules_versions: List[str] = []
    deck_ids: List[Tuple[str, str]] = []
    episode_ids: List[int] = []

    accepted_episodes = 0
    for game_idx in range(args.games):
        if deck_pool:
            deck0_path = rng.choice(deck_pool)
            deck1_path = rng.choice(deck_pool)
            deck0, meta0 = _load_deck(deck0_path)
            deck1, meta1 = _load_deck(deck1_path)
            hero0 = meta0.get("hero")
            hero1 = meta1.get("hero")
            arena0 = meta0.get("arena")
            arena1 = meta1.get("arena")
            deck_pair_id = (_deck_identifier(meta0, deck0_path), _deck_identifier(meta1, deck1_path))
        else:
            deck0 = deck1 = None
            meta0 = meta1 = {}
            hero0 = hero1 = None
            arena0 = arena1 = None
            deck_pair_id = ("random", "random")

        obs, info = env.reset(
            seed=rng.randrange(1, 1 << 30),
            deck0=deck0,
            deck1=deck1,
            hero0=hero0,
            hero1=hero1,
            arena0=arena0,
            arena1=arena1,
        )

        obs = _as_lists(obs)
        legal_actions = info["legal_actions"]
        legal_mask = info["legal_action_mask"]
        actor = info["actor"]

        pass_streak = 0
        max_pass_streak = 0
        steps_no_damage = 0
        max_no_damage = 0

        episode_records: List[int] = []
        bad_episode = False

        done = False
        bot_rng = random.Random(rng.randrange(1, 1 << 30))

        while not done and legal_actions:
            chosen = bot_choose_action(env.state, bot_rng)
            chosen_idx = ACTION_VOCAB.index_for(chosen)
            mask = legal_action_mask(legal_actions, ACTION_VOCAB)
            action_indices = [ACTION_VOCAB.index_for(act) for act in legal_actions]

            if not obs_buffers:
                for key in obs:
                    obs_buffers[key] = []

            for key, value in obs.items():
                obs_buffers[key].append(value.copy())

            legal_masks.append(mask.astype(np.int8))
            legal_action_indices.append(action_indices)
            chosen_actions.append(chosen_idx)
            episode_ids.append(accepted_episodes)
            actors.append(actor)
            rules_versions.append(env.rules_version)
            deck_ids.append(deck_pair_id)

            prev_life = [player.life for player in env.state.players]

            try:
                next_obs, reward, done, next_info = env.step(chosen)
            except IndexError:
                bad_episode = True
                break
            rewards.append(reward)
            dones.append(1 if done else 0)

            new_life = [player.life for player in env.state.players]
            if new_life == prev_life:
                steps_no_damage += 1
            else:
                steps_no_damage = 0
            max_no_damage = max(max_no_damage, steps_no_damage)

            if chosen.typ == ActType.PASS:
                pass_streak += 1
            else:
                pass_streak = 0
            max_pass_streak = max(max_pass_streak, pass_streak)

            obs = _as_lists(next_obs)
            legal_actions = next_info.get("legal_actions", [])
            legal_mask = next_info.get("legal_action_mask")
            actor = next_info.get("actor")

            episode_records.append(1)

        bad_episode = bad_episode or max_pass_streak > args.max_pass_streak or max_no_damage > args.max_no_damage
        if bad_episode:
            # Roll back buffered entries for this episode
            count = len(episode_records)
            if count:
                for key in obs_buffers:
                    obs_buffers[key] = obs_buffers[key][:-count]
                legal_masks[:] = legal_masks[:-count]
                legal_action_indices[:] = legal_action_indices[:-count]
                chosen_actions[:] = chosen_actions[:-count]
                rewards[:] = rewards[:-count]
                dones[:] = dones[:-count]
                actors[:] = actors[:-count]
                rules_versions[:] = rules_versions[:-count]
                deck_ids[:] = deck_ids[:-count]
                episode_ids[:] = episode_ids[:-count]
            continue

        accepted_episodes += 1

    if not legal_masks:
        raise RuntimeError("No valid episodes generated; try relaxing filtering thresholds.")

    dataset: Dict[str, np.ndarray] = {}
    for key, values in obs_buffers.items():
        dataset[f"obs__{key}"] = np.stack(values, axis=0)
    dataset["legal_action_mask"] = np.stack(legal_masks, axis=0)
    dataset["legal_actions"] = np.array([np.array(entry, dtype=np.int32) for entry in legal_action_indices], dtype=object)
    dataset["chosen_action"] = np.array(chosen_actions, dtype=np.int32)
    dataset["reward"] = np.array(rewards, dtype=np.float32)
    dataset["done"] = np.array(dones, dtype=np.int8)
    dataset["actor"] = np.array(actors, dtype=np.int8)
    dataset["rules_version"] = np.array(rules_versions)
    dataset["deck_ids"] = np.array(deck_ids, dtype=object)
    dataset["episode_id"] = np.array(episode_ids, dtype=np.int32)

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


def main() -> None:
    args = _parse_args()
    dataset = generate_dataset(args)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output_path, **dataset)
    print(f"Wrote dataset with {dataset['chosen_action'].shape[0]} transitions to {output_path}")


if __name__ == "__main__":
    main()
