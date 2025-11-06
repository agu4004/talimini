from __future__ import annotations

import random
from typing import Any, List, Optional, Tuple

from .agents import bot_choose_action, current_human_action
from .agents_ml import load_policy as load_ml_policy, load_sb3_policy, ml_bot_choose_action
from .deck import DeckLoadResult
from .engine import apply_action, current_actor_index, enumerate_legal_actions, new_game
from .models import Card, Game, GameState, Phase
from .pretty import _b, _dim, pretty_event


def play_loop(
    mode: str = "human-vs-bot",
    seed: int = 11,
    deck0: Optional[DeckLoadResult] = None,
    deck1: Optional[DeckLoadResult] = None,
    agent0: Optional[str] = None,
    agent1: Optional[str] = None,
    ml_policy_path: Optional[str] = None,
) -> Game:
    def _unpack(deck_result: Optional[DeckLoadResult]) -> Tuple[Optional[List[Card]], Optional[Any], Optional[List[Any]]]:
        if deck_result is None:
            return None, None, None
        cards, meta = deck_result
        hero_meta = meta.get("hero") if isinstance(meta, dict) else None
        arena_meta = meta.get("arena") if isinstance(meta, dict) else None
        arena_list = arena_meta if isinstance(arena_meta, list) else None
        return cards, hero_meta, arena_list

    def _format_arsenal(player):
        if not player.arsenal:
            return '(empty)'
        return ', '.join(card.name for card in player.arsenal)

    deck0_cards, hero0, arena0 = _unpack(deck0)
    deck1_cards, hero1, arena1 = _unpack(deck1)

    game = new_game(
        seed=seed,
        deck0=deck0_cards,
        deck1=deck1_cards,
        hero0=hero0,
        hero1=hero1,
        arena0=arena0,
        arena1=arena1,
    )
    rng = random.Random(seed + 1)

    mode_agents = {
        "human-vs-human": ("human", "human"),
        "human-vs-bot": ("human", "bot"),
        "bot-vs-human": ("bot", "human"),
        "bot-vs-bot": ("bot", "bot"),
        "ml-vs-bot": ("ml", "bot"),
        "bot-vs-ml": ("bot", "ml"),
        "ml-vs-ml": ("ml", "ml"),
        "human-vs-ml": ("human", "ml"),
        "ml-vs-human": ("ml", "human"),
    }
    default_agents = mode_agents.get(mode, ("human", "bot"))
    chosen_agents = [
        (agent0 or default_agents[0]).lower(),
        (agent1 or default_agents[1]).lower(),
    ]
    valid_agents = {"human", "bot", "ml"}
    if any(agent not in valid_agents for agent in chosen_agents):
        raise ValueError(f"Unsupported agent types: {chosen_agents}")

    ml_policy = None
    sb3_policy = None
    if "ml" in chosen_agents and ml_policy_path:
        # Try loading Torch policy first
        ml_policy = load_ml_policy(ml_policy_path)
        if ml_policy is None:
            # Fallback to SB3 policy
            sb3_policy = load_sb3_policy(ml_policy_path)

    def is_human(player_index: int) -> bool:
        return chosen_agents[player_index] == "human"

    def is_ml(player_index: int) -> bool:
        return chosen_agents[player_index] == "ml"

    step = 0
    while True:
        state = game.state
        actor = current_actor_index(state)
        p0, p1 = state.players
        header = f"Step {step} | Turn=P{state.turn} | Actor=P{actor} | Phase={state.phase.value.upper()}"
        if state.awaiting_defense:
            header += " (awaiting DEF)"
        print(_dim("-" * 56))
        print(_b(header))
        print(f"Life  P0: {p0.life}   P1: {p1.life}   |   Hand sizes: ({len(p0.hand)},{len(p1.hand)})")
        print(f"Arsenals P0: {_format_arsenal(p0)}   |   P1: {_format_arsenal(p1)}")
        print(f"Floating resources P0: {state.floating_resources[0]}   |   P1: {state.floating_resources[1]}")
        if state.phase == Phase.ACTION and not state.awaiting_defense:
            print(f"Action points remaining: {state.action_points}")
        print(_dim("-" * 56))

        legal_actions = enumerate_legal_actions(state)
        if is_human(actor):
            action = current_human_action(state)
        elif is_ml(actor):
            action = ml_bot_choose_action(state, policy=ml_policy, sb3_policy=sb3_policy, legal_actions=legal_actions)
        else:
            action = bot_choose_action(state, rng)

        new_state, terminal, event = apply_action(state, action)
        life_now = (new_state.players[0].life, new_state.players[1].life)
        print(pretty_event(event, life_after=life_now))
        game.state = new_state
        step += 1

        if terminal or step > 200:
            p0, p1 = game.state.players
            winner = None
            if p0.life <= 0 and p1.life > 0:
                winner = 1
            if p1.life <= 0 and p0.life > 0:
                winner = 0
            print(_dim("\n-" * 28))
            print(_b("== END =="))
            print(f"Life P0={p0.life}  P1={p1.life}")
            print("Winner:", winner if winner is not None else "Draw/Timeout")
            break

    return game


__all__ = ["play_loop"]
