"""Game initialization module - handles game setup and player initialization.

This module contains functions for initializing a new game, creating players,
loading hero data, and setting up the initial game state.
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

from .config import (
    INTELLECT,
    RANDOM_DECK_ATTACK_CARDS,
    RANDOM_DECK_DEFENSE_CARDS,
    RANDOM_CARD_COSTS,
    RANDOM_CARD_ATTACKS,
    RANDOM_CARD_DEFENSES,
    RANDOM_CARD_PITCH_VALUES,
)
from .models import Card, Game, GameState, Phase, PlayerState, Weapon
from .io.hero_yaml import load_hero_from_yaml
from .io.weapon_yaml import load_weapon_from_arena


def make_random_deck(rng: random.Random) -> List[Card]:
    """Generate a random deck for testing purposes.

    Creates a deck with attack cards and defense cards with randomized stats
    based on configuration constants.

    Args:
        rng: Random number generator for reproducibility

    Returns:
        List of randomly generated cards
    """
    deck: List[Card] = []

    # Generate attack cards
    for _ in range(RANDOM_DECK_ATTACK_CARDS):
        cost = rng.choice(RANDOM_CARD_COSTS)
        attack = rng.choice(RANDOM_CARD_ATTACKS)
        defense = rng.choice(RANDOM_CARD_DEFENSES)
        pitch = rng.choice(RANDOM_CARD_PITCH_VALUES)
        deck.append(
            Card(
                name=f"Strike{cost}-{attack}-{pitch}",
                cost=cost,
                attack=attack,
                defense=defense,
                pitch=pitch,
            )
        )

    # Generate defense cards
    for i in range(RANDOM_DECK_DEFENSE_CARDS):
        defense = rng.choice(RANDOM_CARD_DEFENSES)
        pitch = rng.choice(RANDOM_CARD_PITCH_VALUES)
        deck.append(
            Card(
                name=f"BlockRes{i + 1}-{pitch}",
                cost=0,
                attack=0,
                defense=defense,
                pitch=pitch,
            )
        )

    rng.shuffle(deck)
    return deck


# weapon_from_arena has been moved to io/weapon_yaml.py as load_weapon_from_arena
# This is now imported at the top of the file


def resolve_hero_meta(hero: Optional[Any]) -> Tuple[str, str, Optional[Dict[str, Any]]]:
    """Resolve hero metadata from various input formats.

    Args:
        hero: Hero configuration (dict, string, or None)

    Returns:
        Tuple of (hero_name, ability_text, hero_metadata_dict)
    """
    if isinstance(hero, dict):
        name = str(hero.get("name") or "Generic Hero")
        ability = str(hero.get("ability") or "")
        return name, ability, hero
    if isinstance(hero, str) and hero:
        return hero, "", None
    return "Generic Hero", "", None


def apply_hero_yaml(player: PlayerState, hero_meta: Optional[Dict[str, Any]]) -> None:
    """Apply hero abilities and modifiers from YAML data or metadata.

    All hero-specific logic is now loaded from YAML configuration files
    in the data/heroes directory.

    Args:
        player: Player state to apply hero data to
        hero_meta: Hero metadata dictionary
    """
    hero_yaml = load_hero_from_yaml(player.hero)
    if hero_yaml:
        player.hero = str(hero_yaml.get("name") or player.hero)
        ability_text = hero_yaml.get("ability") or hero_yaml.get("text")
        if ability_text:
            player.hero_text = str(ability_text)
        modifiers = hero_yaml.get("modifiers")
        if isinstance(modifiers, dict):
            player.hero_modifiers = modifiers
    elif hero_meta:
        ability_text = hero_meta.get("ability")
        if ability_text and not player.hero_text:
            player.hero_text = str(ability_text)


def initialize_player(
    deck: List[Card],
    hero: Optional[Any],
    arena: Optional[List[Any]],
) -> PlayerState:
    """Initialize a player with deck, hero, and equipment.

    Args:
        deck: Player's deck of cards
        hero: Hero configuration
        arena: Equipment/weapon configuration

    Returns:
        Initialized PlayerState
    """
    hero_name, hero_text, hero_meta = resolve_hero_meta(hero)

    player = PlayerState(deck=deck, hero=hero_name)
    player.hero_text = hero_text
    player.weapon = load_weapon_from_arena(arena)
    apply_hero_yaml(player, hero_meta)
    player.draw_up_to(INTELLECT)

    return player


def new_game(
    seed: int = 0,
    deck0: Optional[List[Card]] = None,
    deck1: Optional[List[Card]] = None,
    hero0: Optional[Any] = None,
    hero1: Optional[Any] = None,
    arena0: Optional[List[Any]] = None,
    arena1: Optional[List[Any]] = None,
) -> Game:
    """Initialize a new game with two players.

    Args:
        seed: Random seed for reproducibility
        deck0: Player 0's deck (generates random if None)
        deck1: Player 1's deck (generates random if None)
        hero0: Player 0's hero configuration
        hero1: Player 1's hero configuration
        arena0: Player 0's equipment/weapons
        arena1: Player 1's equipment/weapons

    Returns:
        Initialized Game object with both players set up
    """
    rng = random.Random(seed)

    if deck0 is None:
        deck0 = make_random_deck(rng)
    if deck1 is None:
        deck1 = make_random_deck(rng)

    player0 = initialize_player(deck0, hero0, arena0)
    player1 = initialize_player(deck1, hero1, arena1)

    state = GameState(players=[player0, player1], turn=0, phase=Phase.SOT, rng_seed=seed)
    state.floating_resources = [0, 0]
    return Game(state=state)
