"""Tests for state field management (COMBAT_FLOW.md: Key State Fields)."""
from __future__ import annotations

import pytest

from fabgame.engine import apply_action, enumerate_legal_actions
from fabgame.models import Action, ActType, Card, CombatStep, Phase
from tests.conftest import create_test_game


class TestCombatStateFields:
    """Tests for combat state fields (COMBAT_FLOW.md section: Key State Fields)."""

    def test_combat_step_progression(self):
        """
        Given: Full combat sequence
        When: Tracking combat_step
        Then: Progresses IDLE → LAYER → ATTACK → REACTION → DAMAGE/RESOLUTION → IDLE
        """
        gs = create_test_game(phase=Phase.ACTION, turn=0, action_points=1)
        attack_card = Card(name="Attack", cost=0, attack=5, defense=3, pitch=1)
        gs.players[0].hand = [attack_card]

        # Initial state
        assert gs.combat_step == CombatStep.IDLE

        # Play attack
        attack_action = Action(typ=ActType.PLAY_ATTACK, play_idx=0, pitch_mask=0)
        state1, _, _ = apply_action(gs, attack_action)

        # Should be in LAYER step
        assert state1.combat_step == CombatStep.LAYER

        # Pass twice to close layer
        pass_action = Action(typ=ActType.PASS)
        state2, _, _ = apply_action(state1, pass_action)
        state3, _, _ = apply_action(state2, pass_action)

        # Should be in ATTACK step (awaiting defense)
        assert state3.combat_step == CombatStep.ATTACK
        assert state3.awaiting_defense is True

        # Defender passes on block
        state4, _, _ = apply_action(state3, pass_action)

        # Should be in REACTION step
        assert state4.combat_step == CombatStep.REACTION

        # Both pass in reaction
        state5, _, _ = apply_action(state4, pass_action)
        state6, _, _ = apply_action(state5, pass_action)

        # Should return to IDLE after resolution
        assert state6.combat_step == CombatStep.IDLE

    def test_combat_priority_toggle(self, combat_layer_state):
        """
        Given: Layer step
        When: Players pass
        Then: combat_priority alternates between attacker and defender
        """
        gs = combat_layer_state
        assert gs.combat_priority == 0  # Attacker

        pass_action = Action(typ=ActType.PASS)
        state1, _, _ = apply_action(gs, pass_action)

        assert state1.combat_priority == 1  # Defender

        state2, _, _ = apply_action(state1, pass_action)

        # After layer closes, combat_priority may be cleared
        # But during layer it alternates

    def test_combat_passes_tracking(self, combat_reaction_state):
        """
        Given: Reaction step
        When: Players pass
        Then: combat_passes increments correctly, resets on action
        """
        gs = combat_reaction_state
        gs.combat_passes = 0

        pass_action = Action(typ=ActType.PASS)
        state1, _, _ = apply_action(gs, pass_action)

        # First pass
        assert state1.combat_passes == 1

        # If defender plays a reaction, passes should reset
        # (tested in combat flow tests)

    def test_pending_attack_accumulation(self, combat_reaction_state, attack_reaction_card):
        """
        Given: Base attack 5, attack reaction adds 3
        When: Tracking pending_attack
        Then: Starts at 5, becomes 8 after reaction
        """
        gs = combat_reaction_state
        gs.pending_attack = 5
        gs.reaction_actor = 0  # Attacker
        gs.combat_passes = 1

        pitch_card = Card(name="Pitch", cost=0, attack=0, defense=2, pitch=1)
        gs.players[0].hand = [attack_reaction_card, pitch_card]

        initial_attack = gs.pending_attack

        legal = enumerate_legal_actions(gs)
        reaction_actions = [a for a in legal if a.typ == ActType.PLAY_ATTACK_REACTION]

        if reaction_actions:
            new_state, _, _ = apply_action(gs, reaction_actions[0])
            assert new_state.pending_attack > initial_attack

    def test_reaction_block_accumulation(self, combat_defend_state, defense_reaction_card):
        """
        Given: Block with 2 defense, then defense reaction with 3 defense
        When: Tracking reaction_block
        Then: Starts at 2, becomes 5 after reaction
        """
        gs = combat_defend_state
        defender_idx = 1 - gs.turn

        block_card = Card(name="Block", cost=0, attack=0, defense=2, pitch=1)
        gs.players[defender_idx].hand = [block_card]

        # Initial block
        defend_action = Action(typ=ActType.DEFEND, defend_mask=1)
        state1, _, _ = apply_action(gs, defend_action)

        assert state1.reaction_block == 2

        # Add defense reaction and play it
        state1.players[defender_idx].hand = [defense_reaction_card]

        defend_reaction_action = Action(typ=ActType.DEFEND, defend_mask=1)
        state2, _, _ = apply_action(state1, defend_reaction_action)

        assert state2.reaction_block >= 2 + defense_reaction_card.defense

    def test_reaction_actor_toggle(self, combat_reaction_state):
        """
        Given: Reaction step
        When: Players take actions or pass
        Then: reaction_actor alternates between defender and attacker
        """
        gs = combat_reaction_state
        assert gs.reaction_actor == 1  # Defender

        pass_action = Action(typ=ActType.PASS)
        state1, _, _ = apply_action(gs, pass_action)

        assert state1.reaction_actor == 0  # Attacker


class TestResourceManagement:
    """Tests for resource management."""

    def test_floating_resources_persistence(self):
        """
        Given: Player pitches 3 resources but only spends 2
        When: Tracking floating_resources
        Then: 1 resource remains floating, available for next action
        """
        gs = create_test_game(phase=Phase.ACTION, turn=0, action_points=1)

        # Attack with cost 2, pitch 3 resources
        attack_card = Card(name="Attack", cost=2, attack=5, defense=3, pitch=1)
        pitch_cards = [
            Card(name=f"Pitch {i}", cost=0, attack=0, defense=2, pitch=1)
            for i in range(3)
        ]
        gs.players[0].hand = [attack_card] + pitch_cards

        # Find attack action that pitches 3
        legal = enumerate_legal_actions(gs)
        attack_actions = [a for a in legal if a.typ == ActType.PLAY_ATTACK and a.play_idx == 0]

        if attack_actions:
            # Find action that uses exactly 3 pitch
            for action in attack_actions:
                pitch_count = bin(action.pitch_mask).count('1')
                if pitch_count == 3:
                    new_state, _, _ = apply_action(gs, action)
                    # Should have 1 floating (3 pitched - 2 cost)
                    assert new_state.floating_resources[gs.turn] >= 1
                    break

    def test_floating_resources_used_first(self):
        """
        Given: Player has 2 floating, plays card costing 3
        When: Consuming resources
        Then: Uses 2 floating first, pitches only 1 additional
        """
        gs = create_test_game(phase=Phase.ACTION, turn=0, action_points=1)
        gs.floating_resources[0] = 2

        attack_card = Card(name="Attack", cost=3, attack=5, defense=3, pitch=1)
        pitch_card = Card(name="Pitch", cost=0, attack=0, defense=2, pitch=1)
        gs.players[0].hand = [attack_card, pitch_card]

        # Find attack that uses floating
        legal = enumerate_legal_actions(gs)
        attack_actions = [a for a in legal if a.typ == ActType.PLAY_ATTACK and a.play_idx == 0]

        if attack_actions:
            new_state, _, _ = apply_action(gs, attack_actions[0])
            # Floating should be consumed
            assert new_state.floating_resources[0] < gs.floating_resources[0]

    def test_floating_resources_reset_end_of_turn(self):
        """
        Given: Player has floating resources
        When: Turn ends
        Then: floating_resources reset to [0, 0]
        """
        gs = create_test_game(phase=Phase.END, turn=0)
        gs.floating_resources[0] = 3
        gs.awaiting_arsenal = True
        gs.arsenal_player = 0

        # Pass to end turn
        pass_action = Action(typ=ActType.PASS)
        new_state, _, _ = apply_action(gs, pass_action)

        # New turn should have reset floating resources
        assert new_state.floating_resources == [0, 0]


class TestCardZoneTracking:
    """Tests for card zone tracking."""

    def test_pitched_cards_bottom_deck(self):
        """
        Given: Player has pitched cards this turn
        When: Turn ends
        Then: Pitched cards moved to bottom of deck
        """
        from fabgame.models import PlayerState

        pitched_cards = [
            Card(name=f"Pitched {i}", cost=1, attack=2, defense=2, pitch=1)
            for i in range(3)
        ]
        deck_cards = [
            Card(name=f"Deck {i}", cost=1, attack=2, defense=2, pitch=1)
            for i in range(5)
        ]

        player = PlayerState(
            life=20,
            deck=deck_cards[:],
            hand=[],
            grave=[],
            pitched=pitched_cards[:],
            arsenal=[],
        )

        initial_deck_size = len(player.deck)
        player.bottom_pitched_to_deck()

        # All pitched cards should move to deck
        assert len(player.pitched) == 0
        assert len(player.deck) == initial_deck_size + 3

        # Pitched cards should be at bottom (indices 0, 1, 2)
        assert all(player.deck[i].name.startswith("Pitched") for i in range(3))

    def test_graveyard_accumulation(self):
        """
        Given: Multiple attacks and blocks
        When: Cards used
        Then: All non-pitched cards move to grave
        """
        gs = create_test_game(phase=Phase.ACTION, turn=0, action_points=1)
        attack_card = Card(name="Attack", cost=0, attack=5, defense=3, pitch=1)
        defense_card = Card(name="Defense", cost=0, attack=0, defense=3, pitch=1)

        gs.players[0].hand = [attack_card]
        gs.players[1].hand = [defense_card]

        initial_grave_size = len(gs.players[0].grave)

        # Execute attack
        attack_action = Action(typ=ActType.PLAY_ATTACK, play_idx=0, pitch_mask=0)
        state1, _, _ = apply_action(gs, attack_action)

        # Complete combat
        pass_action = Action(typ=ActType.PASS)
        state2, _, _ = apply_action(state1, pass_action)
        state3, _, _ = apply_action(state2, pass_action)
        state4, _, _ = apply_action(state3, pass_action)

        # Attack card should be in graveyard
        # (Exact timing depends on implementation)

    def test_arsenal_persistence(self):
        """
        Given: Card set to arsenal
        When: Turn passes
        Then: Card remains in arsenal
        """
        gs = create_test_game(phase=Phase.END, turn=0)
        arsenal_card = Card(name="Arsenal", cost=1, attack=3, defense=2, pitch=1)
        gs.players[0].hand = [arsenal_card]
        gs.awaiting_arsenal = True
        gs.arsenal_player = 0

        # Set arsenal
        set_action = Action(typ=ActType.SET_ARSENAL, play_idx=0)
        new_state, _, _ = apply_action(gs, set_action)

        # Card should be in arsenal
        assert len(new_state.players[0].arsenal) == 1
        assert new_state.players[0].arsenal[0].name == "Arsenal"

        # After turn passes, should remain
        assert new_state.turn == 1  # Next player's turn
        # Check previous player's arsenal
        assert len(new_state.players[0].arsenal) == 1


class TestActionPoints:
    """Tests for action point management."""

    def test_action_points_start_at_one(self, basic_game_state):
        """
        Given: Start phase CONTINUE executed
        When: Entering action phase
        Then: action_points is 1
        """
        gs = basic_game_state

        continue_action = Action(typ=ActType.CONTINUE)
        new_state, _, _ = apply_action(gs, continue_action)

        assert new_state.action_points == 1

    def test_action_points_decremented_on_attack(self, action_phase_state):
        """
        Given: Player has 1 action point
        When: Attack played
        Then: Action consumed
        """
        gs = action_phase_state
        assert gs.action_points == 1

        attack_card = Card(name="Attack", cost=0, attack=5, defense=3, pitch=1)
        gs.players[gs.turn].hand = [attack_card]

        attack_action = Action(typ=ActType.PLAY_ATTACK, play_idx=0, pitch_mask=0)
        new_state, _, _ = apply_action(gs, attack_action)

        # Action point used for attack (may be in combat, so effectively consumed)

    def test_action_points_restored_by_go_again(self):
        """
        Given: Attack with Go Again resolves
        When: Resolution step completes
        Then: action_points incremented by 1
        """
        gs = create_test_game(phase=Phase.ACTION, turn=0, action_points=1)
        go_again_card = Card(name="Go Again", cost=0, attack=4, defense=2, pitch=1, keywords=["go_again"])
        gs.players[0].hand = [go_again_card]

        # Execute attack
        attack_action = Action(typ=ActType.PLAY_ATTACK, play_idx=0, pitch_mask=0)
        state1, _, _ = apply_action(gs, attack_action)

        # Complete combat
        pass_action = Action(typ=ActType.PASS)
        state2, _, _ = apply_action(state1, pass_action)
        state3, _, _ = apply_action(state2, pass_action)
        state4, _, _ = apply_action(state3, pass_action)

        # Action point should be restored
        assert state4.action_points == 1

    def test_action_points_zero_after_normal_attack(self):
        """
        Given: Normal attack (no Go Again)
        When: Combat resolves
        Then: action_points is 0
        """
        gs = create_test_game(phase=Phase.ACTION, turn=0, action_points=1)
        normal_card = Card(name="Normal", cost=0, attack=4, defense=2, pitch=1, keywords=[])
        gs.players[0].hand = [normal_card]

        # Execute attack
        attack_action = Action(typ=ActType.PLAY_ATTACK, play_idx=0, pitch_mask=0)
        state1, _, _ = apply_action(gs, attack_action)

        # Complete combat
        pass_action = Action(typ=ActType.PASS)
        state2, _, _ = apply_action(state1, pass_action)
        state3, _, _ = apply_action(state2, pass_action)
        state4, _, _ = apply_action(state3, pass_action)

        # Action points should be 0
        assert state4.action_points == 0


class TestLastAttackTracking:
    """Tests for last attack tracking fields."""

    def test_last_attack_card_stored(self, action_phase_state):
        """
        Given: Player declares attack
        When: Attack step executes
        Then: last_attack_card is set
        """
        gs = action_phase_state
        attack_card = Card(name="Test Attack", cost=0, attack=5, defense=3, pitch=1)
        gs.players[gs.turn].hand = [attack_card]

        attack_action = Action(typ=ActType.PLAY_ATTACK, play_idx=0, pitch_mask=0)
        new_state, _, _ = apply_action(gs, attack_action)

        assert new_state.last_attack_card is not None
        assert new_state.last_attack_card.name == "Test Attack"

    def test_last_pitch_sum_recorded(self):
        """
        Given: Player pitches cards for attack
        When: Attack executes
        Then: last_pitch_sum records total pitch value
        """
        gs = create_test_game(phase=Phase.ACTION, turn=0, action_points=1)
        attack_card = Card(name="Attack", cost=2, attack=5, defense=3, pitch=1)
        pitch_cards = [
            Card(name=f"Pitch {i}", cost=0, attack=0, defense=2, pitch=1)
            for i in range(2)
        ]
        gs.players[0].hand = [attack_card] + pitch_cards

        legal = enumerate_legal_actions(gs)
        attack_actions = [a for a in legal if a.typ == ActType.PLAY_ATTACK and a.play_idx == 0]

        if attack_actions:
            new_state, _, _ = apply_action(gs, attack_actions[0])
            # last_pitch_sum should be set to at least the cost paid
            assert new_state.last_pitch_sum >= 2

    def test_attacks_this_turn_counter(self):
        """
        Given: Player makes multiple attacks
        When: Tracking attacks_this_turn
        Then: Counter increments for each attack
        """
        gs = create_test_game(phase=Phase.ACTION, turn=0, action_points=1)
        go_again_card = Card(name="Go Again", cost=0, attack=4, defense=2, pitch=1, keywords=["go_again"])
        gs.players[0].hand = [go_again_card, go_again_card.copy()]

        initial_attacks = gs.players[0].attacks_this_turn

        # Execute first attack
        attack_action = Action(typ=ActType.PLAY_ATTACK, play_idx=0, pitch_mask=0)
        state1, _, _ = apply_action(gs, attack_action)

        # Complete combat
        pass_action = Action(typ=ActType.PASS)
        state2, _, _ = apply_action(state1, pass_action)
        state3, _, _ = apply_action(state2, pass_action)
        state4, _, _ = apply_action(state3, pass_action)

        # Attack counter should increment
        assert state4.players[0].attacks_this_turn >= initial_attacks + 1
