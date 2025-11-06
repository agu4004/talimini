#!/usr/bin/env python
"""
Cross-play evaluation harness for fabgame agents.

Example:
    python -m scripts.eval_agents --agents bot --agents ml:checkpoints/policy_ep100.pt --games 50
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:  # pragma: no cover - dependency guard
    import numpy as np
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("scripts/eval_agents.py requires numpy to be installed") from exc

from fabgame import deck as deck_lib
from fabgame.agents import bot_choose_action
from fabgame.agents_ml import load_policy as load_ml_policy, ml_bot_choose_action
from fabgame.rl import FabgameEnv


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate agents head-to-head under fixed seeds.")
    parser.add_argument("--agents", action="append", required=True, help="Agent spec: bot or ml:/path/to/checkpoint.pt")
    parser.add_argument("--games", type=int, default=50, help="Number of games per matchup.")
    parser.add_argument("--seed", type=int, default=1234, help="Base seed for reproducibility.")
    parser.add_argument("--rules-version", type=str, default="standard", help="Rules version to evaluate under.")
    parser.add_argument("--deck-pool", type=str, default=None, help="Optional directory of deck JSON files.")
    parser.add_argument("--deck-pool-version", type=str, default="unknown", help="Identifier for the deck pool used.")
    parser.add_argument("--output", type=str, default=None, help="Optional JSON file to store results.")
    return parser.parse_args()


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def _load_deck_pool(path: Optional[str]) -> List[str]:
    if not path:
        return []
    directory = Path(path)
    if not directory.is_dir():
        raise FileNotFoundError(f"Deck pool directory not found: {path}")
    return [str(p) for p in sorted(directory.glob("*.json"))]


def _load_deck(path: str) -> Tuple[List, Dict[str, any]]:
    return deck_lib.load_deck_from_json(path)


@dataclass
class AgentSpec:
    label: str
    agent_type: str
    path: Optional[str] = None
    policy_cache: Optional[object] = None


class Agent:
    def choose(self, env: FabgameEnv, legal_actions: Sequence) -> any:
        raise NotImplementedError


class BotAgent(Agent):
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)

    def choose(self, env: FabgameEnv, legal_actions: Sequence) -> any:
        return bot_choose_action(env.state, self.rng)


class MLAgent(Agent):
    def __init__(self, policy: Optional[object]) -> None:
        self.policy = policy

    def choose(self, env: FabgameEnv, legal_actions: Sequence) -> any:
        return ml_bot_choose_action(env.state, policy=self.policy, legal_actions=legal_actions)


def parse_agent_specs(raw_specs: Iterable[str]) -> List[AgentSpec]:
    specs: List[AgentSpec] = []
    for entry in raw_specs:
        if entry.startswith("ml:"):
            path = entry.split(":", 1)[1]
            label = Path(path).stem or "ml"
            specs.append(AgentSpec(label=label, agent_type="ml", path=path))
        elif entry == "bot":
            specs.append(AgentSpec(label="bot", agent_type="bot"))
        else:
            raise ValueError(f"Unsupported agent spec: {entry}")
    return specs


def build_agent(spec: AgentSpec, seed: int) -> Agent:
    if spec.agent_type == "bot":
        return BotAgent(seed)
    if spec.agent_type == "ml":
        if spec.policy_cache is None:
            spec.policy_cache = load_ml_policy(spec.path or "", device="cpu")
        return MLAgent(spec.policy_cache)
    raise ValueError(f"Unknown agent type: {spec.agent_type}")


def run_match(
    env: FabgameEnv,
    agent0: Agent,
    agent1: Agent,
    *,
    deck0: Optional[List] = None,
    deck1: Optional[List] = None,
    hero0: Optional[dict] = None,
    hero1: Optional[dict] = None,
    arena0: Optional[List] = None,
    arena1: Optional[List] = None,
    seed: int,
) -> Tuple[Optional[int], int, int, int]:
    obs, info = env.reset(
        seed=seed,
        deck0=deck0,
        deck1=deck1,
        hero0=hero0,
        hero1=hero1,
        arena0=arena0,
        arena1=arena1,
    )
    done = False
    turns = 0
    while not done:
        actor = info["actor"]
        legal_actions = info.get("legal_actions", [])
        if actor == 0:
            action = agent0.choose(env, legal_actions)
        else:
            action = agent1.choose(env, legal_actions)
        obs, _, done, info = env.step(action)
        turns += 1
    life0 = env.state.players[0].life
    life1 = env.state.players[1].life
    if life0 > life1:
        winner = 0
    elif life1 > life0:
        winner = 1
    else:
        winner = None
    return winner, life0, life1, turns


def evaluate_pair(
    env: FabgameEnv,
    spec_a: AgentSpec,
    spec_b: AgentSpec,
    *,
    games: int,
    rng: random.Random,
    deck_pool: Sequence[str],
) -> Dict[str, float]:
    wins = {0: 0, 1: 0}
    life_totals = {0: 0.0, 1: 0.0}
    total_turns = 0

    for game_idx in range(games):
        seed = rng.randrange(1, 1 << 30)

        deck0 = deck1 = hero0 = hero1 = arena0 = arena1 = None
        if deck_pool:
            deck0_path = rng.choice(deck_pool)
            deck1_path = rng.choice(deck_pool)
            deck0, meta0 = _load_deck(deck0_path)
            deck1, meta1 = _load_deck(deck1_path)
            hero0 = meta0.get("hero")
            hero1 = meta1.get("hero")
            arena0 = meta0.get("arena")
            arena1 = meta1.get("arena")

        agent0 = build_agent(spec_a, seed + 1)
        agent1 = build_agent(spec_b, seed + 2)

        winner, life0, life1, turns = run_match(
            env,
            agent0,
            agent1,
            deck0=deck0,
            deck1=deck1,
            hero0=hero0,
            hero1=hero1,
            arena0=arena0 if isinstance(arena0, list) else None,
            arena1=arena1 if isinstance(arena1, list) else None,
            seed=seed,
        )
        if winner is not None:
            wins[winner] += 1
        life_totals[0] += life0
        life_totals[1] += life1
        total_turns += turns

    return {
        "wins_a": wins[0],
        "wins_b": wins[1],
        "win_rate_a": wins[0] / games,
        "win_rate_b": wins[1] / games,
        "avg_life_a": life_totals[0] / games,
        "avg_life_b": life_totals[1] / games,
        "avg_turns": total_turns / games,
    }


def main() -> None:
    args = _parse_args()
    rng = random.Random(args.seed)
    deck_pool = _load_deck_pool(args.deck_pool)
    specs = parse_agent_specs(args.agents)

    env = FabgameEnv(rules_version=args.rules_version)

    engine_commit = _git_commit()
    metadata = {
        "rules_version": args.rules_version,
        "engine_commit": engine_commit,
        "deck_pool_version": args.deck_pool_version,
        "games_per_matchup": args.games,
        "agent_specs": [spec.__dict__ for spec in specs],
    }
    print(json.dumps(metadata, indent=2))

    results: Dict[str, Dict[str, float]] = {}

    for spec_a in specs:
        for spec_b in specs:
            key = f"{spec_a.label}_vs_{spec_b.label}"
            stats = evaluate_pair(env, spec_a, spec_b, games=args.games, rng=rng, deck_pool=deck_pool)
            results[key] = stats
            print(f"\nMatchup {key}:")
            print(f"  win_rate_{spec_a.label}: {stats['win_rate_a']:.3f}")
            print(f"  win_rate_{spec_b.label}: {stats['win_rate_b']:.3f}")
            print(f"  avg_life_{spec_a.label}: {stats['avg_life_a']:.2f}")
            print(f"  avg_life_{spec_b.label}: {stats['avg_life_b']:.2f}")
            print(f"  avg_turns: {stats['avg_turns']:.2f}")

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"metadata": metadata, "results": results}
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nSaved evaluation summary to {output_path}")


if __name__ == "__main__":
    main()
