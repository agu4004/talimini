"""Pytest configuration and shared fixtures for fabgame tests."""
from __future__ import annotations

from typing import List, Optional

import pytest

from fabgame.config import INTELLECT, STARTING_LIFE
from fabgame.engine import new_game
from fabgame.models import Action, ActType, Card, CombatStep, GameState, Phase, PlayerState, Weapon


@pytest.fixture
def simple_attack_card() -> Card:
    """Create a simple attack card for testing."""
    return Card(
        name="Simple Attack",
        cost=1,
        attack=4,
        defense=3,
        pitch=1,
        keywords=[],
    )


@pytest.fixture
def go_again_attack_card() -> Card:
    """Create an attack card with Go Again."""
    return Card(
        name="Go Again Attack",
        cost=2,
        attack=5,
        defense=2,
        pitch=1,
        keywords=["go_again"],
    )


@pytest.fixture
def defense_reaction_card() -> Card:
    """Create a defense reaction card."""
    return Card(
        name="Defense Reaction",
        cost=0,
        attack=0,
        defense=4,
        pitch=1,
        keywords=["defense_reaction", "reaction"],
    )


@pytest.fixture
def attack_reaction_card() -> Card:
    """Create an attack reaction card."""
    return Card(
        name="Attack Reaction",
        cost=1,
        attack=3,
        defense=0,
        pitch=1,
        keywords=["attack_reaction", "reaction"],
    )


@pytest.fixture
def simple_weapon() -> Weapon:
    """Create a simple weapon for testing."""
    return Weapon(
        name="Simple Weapon",
        base_attack=2,
        cost=0,
        once_per_turn=True,
        used_this_turn=False,
        keywords=[],
    )


@pytest.fixture
def go_again_weapon() -> Weapon:
    """Create a weapon with Go Again."""
    return Weapon(
        name="Go Again Weapon",
        base_attack=1,
        cost=1,
        once_per_turn=True,
        used_this_turn=False,
        keywords=["go_again"],
    )


@pytest.fixture
def basic_game_state() -> GameState:
    """Create a basic game state for testing."""
    game = new_game(seed=42)
    return game.state


@pytest.fixture
def action_phase_state() -> GameState:
    """Create a game state in action phase with action points."""
    game = new_game(seed=42)
    gs = game.state
    gs.phase = Phase.ACTION
    gs.action_points = 1
    return gs


@pytest.fixture
def combat_layer_state(action_phase_state: GameState, simple_attack_card: Card) -> GameState:
    """Create a game state in combat layer step."""
    gs = action_phase_state
    gs.combat_step = CombatStep.LAYER
    gs.combat_priority = 0
    gs.pending_attack = simple_attack_card.attack
    gs.last_attack_card = simple_attack_card
    return gs


@pytest.fixture
def combat_defend_state(combat_layer_state: GameState) -> GameState:
    """Create a game state in defend step."""
    gs = combat_layer_state
    gs.combat_step = CombatStep.ATTACK
    gs.awaiting_defense = True
    return gs


@pytest.fixture
def combat_reaction_state(combat_defend_state: GameState) -> GameState:
    """Create a game state in reaction step."""
    gs = combat_defend_state
    gs.combat_step = CombatStep.REACTION
    gs.awaiting_defense = False
    gs.reaction_actor = 1  # Defender
    gs.reaction_block = 3  # Some block declared
    gs.combat_passes = 0
    return gs


@pytest.fixture
def end_phase_state(basic_game_state: GameState) -> GameState:
    """Create a game state in end phase."""
    gs = basic_game_state
    gs.phase = Phase.END
    gs.awaiting_arsenal = True
    gs.arsenal_player = gs.turn
    return gs


@pytest.fixture
def capture_events():
    """Fixture to capture events from action execution."""
    events = []

    def add_event(event: dict):
        events.append(event)

    return events, add_event


def create_player_with_cards(
    cards: List[Card],
    life: int = STARTING_LIFE,
    weapon: Optional[Weapon] = None,
    deck_size: int = 20,
) -> PlayerState:
    """Helper to create a player with specific cards in hand.

    Args:
        cards: Cards to place in player's hand
        life: Player life total
        weapon: Optional weapon to equip
        deck_size: Number of generic cards to add to deck

    Returns:
        PlayerState with specified configuration
    """
    # Create generic deck cards
    deck = [
        Card(name=f"Deck Card {i}", cost=1, attack=2, defense=2, pitch=1, keywords=[])
        for i in range(deck_size)
    ]

    return PlayerState(
        life=life,
        deck=deck,
        hand=cards[:],
        grave=[],
        pitched=[],
        arsenal=[],
        hero="Test Hero",
        weapon=weapon,
        attacks_this_turn=0,
    )


def create_test_game(
    player0_hand: Optional[List[Card]] = None,
    player1_hand: Optional[List[Card]] = None,
    phase: Phase = Phase.SOT,
    turn: int = 0,
    action_points: int = 0,
    player0_weapon: Optional[Weapon] = None,
    player1_weapon: Optional[Weapon] = None,
) -> GameState:
    """Create a customized game state for testing.

    Args:
        player0_hand: Cards for player 0's hand
        player1_hand: Cards for player 1's hand
        phase: Game phase
        turn: Active player index
        action_points: Number of action points
        player0_weapon: Weapon for player 0
        player1_weapon: Weapon for player 1

    Returns:
        Configured GameState
    """
    p0_cards = player0_hand if player0_hand else []
    p1_cards = player1_hand if player1_hand else []

    player0 = create_player_with_cards(p0_cards, weapon=player0_weapon)
    player1 = create_player_with_cards(p1_cards, weapon=player1_weapon)

    return GameState(
        players=[player0, player1],
        turn=turn,
        phase=phase,
        action_points=action_points,
        floating_resources=[0, 0],
    )


def skip_layer_step(state: GameState) -> GameState:
    """Skip through the combat layer step with two passes.

    After an attack is declared, the game enters the LAYER step which requires
    two passes (per COMBAT_FLOW.md) before proceeding to the ATTACK/DEFEND step.

    Args:
        state: Game state currently in LAYER step

    Returns:
        Game state after layer step (ready for defend)
    """
    from fabgame.engine import apply_action

    pass_action = Action(typ=ActType.PASS)

    # First pass (attacker)
    state, _, _ = apply_action(state, pass_action)

    # Second pass (defender) - closes layer
    state, _, _ = apply_action(state, pass_action)

    return state


def execute_full_combat(
    gs: GameState,
    attack_action: Action,
    defend_action: Optional[Action] = None,
    attacker_reactions: Optional[List[Action]] = None,
    defender_reactions: Optional[List[Action]] = None,
) -> GameState:
    """Execute a full combat sequence including layer step.

    Args:
        gs: Initial game state
        attack_action: Attack action to execute
        defend_action: Optional defend action (None = pass)
        attacker_reactions: Optional list of attacker reactions
        defender_reactions: Optional list of defender reactions

    Returns:
        Game state after combat resolves
    """
    from fabgame.engine import apply_action

    # 1. Declare attack
    state, _, _ = apply_action(gs, attack_action)

    # 2. Skip layer step
    state = skip_layer_step(state)

    # 3. Defend step
    if defend_action:
        state, _, _ = apply_action(state, defend_action)
    else:
        state, _, _ = apply_action(state, Action(typ=ActType.PASS))

    # 4. Reaction step - defender reactions
    if defender_reactions:
        for reaction in defender_reactions:
            state, _, _ = apply_action(state, reaction)
        # After defense reaction, priority goes to attacker
        # Attacker passes (combat_passes = 0, priority back to defender)
        state, _, _ = apply_action(state, Action(typ=ActType.PASS))
        # Defender passes (combat_passes = 1, priority to attacker)
        state, _, _ = apply_action(state, Action(typ=ActType.PASS))
    else:
        # Defender passes (priority goes to attacker, combat_passes = 1)
        state, _, _ = apply_action(state, Action(typ=ActType.PASS))

    # 5. Reaction step - attacker reactions
    if attacker_reactions:
        for reaction in attacker_reactions:
            state, _, _ = apply_action(state, reaction)
        # After attack reaction, priority goes to defender
        # Defender passes (combat_passes = 0, priority to attacker)
        state, _, _ = apply_action(state, Action(typ=ActType.PASS))
        # Attacker passes (combat_passes = 1, will resolve)
        state, _, _ = apply_action(state, Action(typ=ActType.PASS))
    else:
        # Attacker passes to resolve combat (combat_passes should be 1)
        state, _, _ = apply_action(state, Action(typ=ActType.PASS))

    return state
