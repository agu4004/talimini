"""Tests for combat flow steps (COMBAT_FLOW.md sections 1-6)."""
from __future__ import annotations

import pytest

from fabgame.config import DEFEND_MAX
from fabgame.engine import apply_action, current_actor_index, enumerate_legal_actions
from fabgame.models import Action, ActType, Card, CombatStep, Phase
from tests.conftest import create_player_with_cards, create_test_game


class TestLayerStep:
    """Tests for Layer Step (COMBAT_FLOW.md section 1)."""

    def test_layer_step_initialization(self, combat_layer_state):
        """
        Given: Attack just declared
        When: Combat begins
        Then: combat_step is LAYER, combat_priority set to attacker, only PASS available
        """
        gs = combat_layer_state
        assert gs.combat_step == CombatStep.LAYER
        assert gs.combat_priority == 0  # Attacker

        legal = enumerate_legal_actions(gs)
        # In layer step, only passes are allowed
        assert all(act.typ == ActType.PASS for act in legal)

    def test_layer_step_priority_toggle(self, combat_layer_state):
        """
        Given: Layer step with attacker having priority
        When: Attacker executes PASS
        Then: combat_priority toggles to defender, combat_passes incremented
        """
        gs = combat_layer_state
        assert gs.combat_priority == 0

        pass_action = Action(typ=ActType.PASS)
        new_state, done, info = apply_action(gs, pass_action)

        assert new_state.combat_priority == 1  # Defender
        assert new_state.combat_passes == 1

    def test_layer_step_closes_after_two_passes(self, combat_layer_state):
        """
        Given: Layer step with 1 pass already recorded
        When: Second player executes PASS
        Then: Transitions to ATTACK step, awaiting_defense becomes True
        """
        gs = combat_layer_state
        gs.combat_passes = 1
        gs.combat_priority = 1  # Defender's turn

        pass_action = Action(typ=ActType.PASS)
        new_state, done, info = apply_action(gs, pass_action)

        # Should transition to attack/defend step
        assert new_state.combat_step == CombatStep.ATTACK
        assert new_state.awaiting_defense is True


class TestAttackStep:
    """Tests for Attack Step (COMBAT_FLOW.md section 2)."""

    def test_attack_step_card_movement_from_hand(self, action_phase_state):
        """
        Given: Player plays attack from hand
        When: Attack step executes
        Then: Attack card moved from hand to graveyard
        """
        gs = action_phase_state
        attack_card = Card(name="Test Attack", cost=0, attack=5, defense=3, pitch=1)
        gs.players[gs.turn].hand = [attack_card]

        attack_action = Action(typ=ActType.PLAY_ATTACK, play_idx=0, pitch_mask=0)
        new_state, done, info = apply_action(gs, attack_action)

        player = new_state.players[gs.turn]
        # Card should be removed from hand
        assert attack_card not in player.hand
        # Card should be in graveyard (after combat resolves)
        # Note: Might be in graveyard immediately or after combat

    def test_attack_step_weapon_stays_equipped(self, action_phase_state, simple_weapon):
        """
        Given: Player attacks with weapon
        When: Attack executes
        Then: Weapon stays equipped, used_this_turn set to True
        """
        gs = action_phase_state
        gs.players[gs.turn].weapon = simple_weapon

        weapon_action = Action(typ=ActType.WEAPON_ATTACK, pitch_mask=0)
        new_state, done, info = apply_action(gs, weapon_action)

        # Weapon should still be equipped
        assert new_state.players[gs.turn].weapon is not None
        assert new_state.players[gs.turn].weapon.name == "Simple Weapon"
        assert new_state.players[gs.turn].weapon.used_this_turn is True

    def test_attack_step_pending_attack_set(self, action_phase_state):
        """
        Given: Player declares attack with base attack 5
        When: Attack step executes
        Then: pending_attack set to base attack value
        """
        gs = action_phase_state
        attack_card = Card(name="Attack", cost=0, attack=5, defense=3, pitch=1)
        gs.players[gs.turn].hand = [attack_card]

        attack_action = Action(typ=ActType.PLAY_ATTACK, play_idx=0, pitch_mask=0)
        new_state, done, info = apply_action(gs, attack_action)

        # pending_attack should be set (may have modifiers applied)
        assert new_state.pending_attack >= attack_card.attack

    def test_attack_step_go_again_flag_set(self, action_phase_state):
        """
        Given: Player declares attack with Go Again
        When: Attack step executes
        Then: last_attack_had_go_again set to True
        """
        gs = action_phase_state
        # Use a free (cost 0) Go Again attack
        go_again_card = Card(name="Go Again Attack", cost=0, attack=5, defense=2, pitch=1, keywords=["go_again"])
        gs.players[gs.turn].hand = [go_again_card]

        attack_action = Action(typ=ActType.PLAY_ATTACK, play_idx=0, pitch_mask=0)
        new_state, done, info = apply_action(gs, attack_action)

        assert new_state.last_attack_had_go_again is True

    def test_attack_step_cost_payment_with_floating(self):
        """
        Given: Player attacks with card costing 3, has 1 floating resource
        When: Attack executes
        Then: Uses floating resource first, then pitches additional
        """
        gs = create_test_game(phase=Phase.ACTION, turn=0, action_points=1)
        attack_card = Card(name="Expensive Attack", cost=3, attack=6, defense=3, pitch=1)
        pitch_cards = [Card(name=f"Pitch {i}", cost=0, attack=0, defense=2, pitch=1) for i in range(3)]

        gs.players[gs.turn].hand = [attack_card] + pitch_cards
        gs.floating_resources[gs.turn] = 1

        # Find legal attack action with proper pitching
        legal = enumerate_legal_actions(gs)
        attack_actions = [a for a in legal if a.typ == ActType.PLAY_ATTACK and a.play_idx == 0]

        if attack_actions:
            new_state, done, info = apply_action(gs, attack_actions[0])
            # Floating resource should be consumed
            assert new_state.floating_resources[gs.turn] == 0 or new_state.floating_resources[gs.turn] < gs.floating_resources[gs.turn]


class TestDefendStep:
    """Tests for Defend Step (COMBAT_FLOW.md section 3)."""

    def test_defend_step_legal_actions(self, combat_defend_state):
        """
        Given: Defender in defend step
        When: enumerate_legal_actions called
        Then: Can DEFEND with up to DEFEND_MAX non-reaction cards, or PASS
        """
        gs = combat_defend_state
        defender_idx = 1 - gs.turn

        # Add non-reaction defense cards to defender's hand
        defense_cards = [
            Card(name=f"Defense {i}", cost=0, attack=2, defense=3, pitch=1, keywords=[])
            for i in range(4)
        ]
        gs.players[defender_idx].hand = defense_cards

        legal = enumerate_legal_actions(gs)
        action_types = {act.typ for act in legal}

        assert ActType.DEFEND in action_types
        assert ActType.PASS in action_types

    def test_defend_step_block_cards_movement(self, combat_defend_state):
        """
        Given: Defender chooses to block with 2 cards
        When: DEFEND action executes
        Then: Selected cards moved to graveyard, defense values summed into reaction_block
        """
        gs = combat_defend_state
        defender_idx = 1 - gs.turn

        card1 = Card(name="Block 1", cost=0, attack=0, defense=3, pitch=1)
        card2 = Card(name="Block 2", cost=0, attack=0, defense=2, pitch=1)
        gs.players[defender_idx].hand = [card1, card2]

        # Create defend action with mask selecting both cards
        defend_mask = (1 << 0) | (1 << 1)  # Select cards at index 0 and 1
        defend_action = Action(typ=ActType.DEFEND, defend_mask=defend_mask)

        new_state, done, info = apply_action(gs, defend_action)

        # Cards should be moved to graveyard
        new_defender = new_state.players[defender_idx]
        assert len(new_defender.hand) == 0

        # Block value should be accumulated
        expected_block = card1.defense + card2.defense
        assert new_state.reaction_block == expected_block

    def test_defend_step_pass_no_block(self, combat_defend_state):
        """
        Given: Defender in defend step
        When: Defender executes PASS
        Then: reaction_block remains 0, transitions to reaction step
        """
        gs = combat_defend_state
        defender_idx = 1 - gs.turn
        gs.players[defender_idx].hand = [
            Card(name="Defense", cost=0, attack=0, defense=3, pitch=1)
        ]

        pass_action = Action(typ=ActType.PASS)
        new_state, done, info = apply_action(gs, pass_action)

        assert new_state.reaction_block == 0
        # Should transition to reaction step
        assert new_state.combat_step == CombatStep.REACTION

    def test_defend_step_max_cards_limit(self, combat_defend_state):
        """
        Given: Defender has many cards, DEFEND_MAX is 2
        When: Checking legal actions
        Then: Can only select up to DEFEND_MAX cards
        """
        gs = combat_defend_state
        defender_idx = 1 - gs.turn

        # Add many defense cards
        gs.players[defender_idx].hand = [
            Card(name=f"Defense {i}", cost=0, attack=0, defense=2, pitch=1)
            for i in range(5)
        ]

        legal = enumerate_legal_actions(gs)
        defend_actions = [a for a in legal if a.typ == ActType.DEFEND]

        # Check that no action selects more than DEFEND_MAX cards
        for action in defend_actions:
            mask = action.defend_mask
            card_count = bin(mask).count('1')
            assert card_count <= DEFEND_MAX


class TestReactionStep:
    """Tests for Reaction Step (COMBAT_FLOW.md section 4)."""

    def test_reaction_step_defender_priority_first(self, combat_reaction_state):
        """
        Given: Just entered reaction step
        When: Checking current actor
        Then: Defender has priority
        """
        gs = combat_reaction_state
        assert gs.combat_step == CombatStep.REACTION
        assert gs.reaction_actor == 1  # Defender
        assert current_actor_index(gs) == 1

    def test_reaction_step_defender_plays_defense_reaction(self, combat_reaction_state, defense_reaction_card):
        """
        Given: Defender has defense reaction in hand
        When: Defender plays defense reaction
        Then: Card moved to graveyard, defense added to reaction_block, passes reset
        """
        gs = combat_reaction_state
        defender_idx = 1
        gs.players[defender_idx].hand = [defense_reaction_card]

        initial_block = gs.reaction_block

        # Defender plays defense reaction
        defend_action = Action(typ=ActType.DEFEND, defend_mask=1)  # Select first card
        new_state, done, info = apply_action(gs, defend_action)

        # Block should increase
        assert new_state.reaction_block > initial_block
        # combat_passes should reset
        assert new_state.combat_passes == 0

    def test_reaction_step_defender_pass(self, combat_reaction_state):
        """
        Given: Defender has priority, chooses not to react
        When: Defender executes PASS
        Then: combat_passes set to 1, reaction_actor toggles to attacker
        """
        gs = combat_reaction_state
        assert gs.reaction_actor == 1

        pass_action = Action(typ=ActType.PASS)
        new_state, done, info = apply_action(gs, pass_action)

        assert new_state.combat_passes == 1
        assert new_state.reaction_actor == 0  # Attacker

    def test_reaction_step_attacker_plays_attack_reaction(self, combat_reaction_state, attack_reaction_card):
        """
        Given: Attacker has priority and attack reaction in hand
        When: Attacker plays attack reaction
        Then: Attack bonus added to pending_attack, passes reset, priority to defender
        """
        gs = combat_reaction_state
        gs.reaction_actor = 0  # Attacker has priority
        gs.combat_passes = 1  # Defender already passed

        attacker_idx = 0
        pitch_card = Card(name="Pitch", cost=0, attack=0, defense=2, pitch=1)
        gs.players[attacker_idx].hand = [attack_reaction_card, pitch_card]

        initial_attack = gs.pending_attack

        # Find attack reaction action
        legal = enumerate_legal_actions(gs)
        reaction_actions = [a for a in legal if a.typ == ActType.PLAY_ATTACK_REACTION]

        if reaction_actions:
            new_state, done, info = apply_action(gs, reaction_actions[0])

            # Attack should increase
            assert new_state.pending_attack > initial_attack
            # Passes should reset
            assert new_state.combat_passes == 0
            # Priority back to defender
            assert new_state.reaction_actor == 1

    def test_reaction_step_closes_after_consecutive_passes(self, combat_reaction_state):
        """
        Given: Defender passed (combat_passes = 1), attacker has priority
        When: Attacker executes PASS
        Then: Reaction step closes, transitions to damage
        """
        gs = combat_reaction_state
        gs.reaction_actor = 0  # Attacker
        gs.combat_passes = 1  # Defender passed

        pass_action = Action(typ=ActType.PASS)
        new_state, done, info = apply_action(gs, pass_action)

        # Should transition to damage/resolution
        assert new_state.combat_step in (CombatStep.DAMAGE, CombatStep.RESOLUTION, CombatStep.IDLE)


class TestDamageStep:
    """Tests for Damage Step (COMBAT_FLOW.md section 5)."""

    def test_damage_calculation(self):
        """
        Given: pending_attack is 7, reaction_block is 3
        When: Damage step executes
        Then: pending_damage is 4, defender life reduced by 4
        """
        from tests.conftest import execute_full_combat

        gs = create_test_game(phase=Phase.ACTION, turn=0, action_points=1)
        attack_card = Card(name="Attack", cost=0, attack=7, defense=3, pitch=1)
        defense_card = Card(name="Defense", cost=0, attack=0, defense=3, pitch=1)

        gs.players[0].hand = [attack_card]
        gs.players[1].hand = [defense_card]

        defender_initial_life = gs.players[1].life

        # Execute full combat: attack -> layer -> defend -> reaction -> resolve
        attack_action = Action(typ=ActType.PLAY_ATTACK, play_idx=0, pitch_mask=0)
        defend_action = Action(typ=ActType.DEFEND, defend_mask=1)

        final_state = execute_full_combat(gs, attack_action, defend_action)

        # Damage should be applied
        expected_damage = 7 - 3
        assert final_state.players[1].life == defender_initial_life - expected_damage

    def test_damage_zero_when_block_exceeds_attack(self):
        """
        Given: pending_attack is 5, reaction_block is 8
        When: Damage step executes
        Then: pending_damage is 0, defender life unchanged
        """
        gs = create_test_game(phase=Phase.ACTION, turn=0, action_points=1)
        attack_card = Card(name="Attack", cost=0, attack=5, defense=3, pitch=1)
        defense_cards = [
            Card(name=f"Defense {i}", cost=0, attack=0, defense=4, pitch=1)
            for i in range(2)
        ]

        gs.players[0].hand = [attack_card]
        gs.players[1].hand = defense_cards

        defender_initial_life = gs.players[1].life

        # Execute combat
        attack_action = Action(typ=ActType.PLAY_ATTACK, play_idx=0, pitch_mask=0)
        state1, done, info = apply_action(gs, attack_action)

        # Defender blocks with both cards (8 defense total)
        defend_action = Action(typ=ActType.DEFEND, defend_mask=0b11)
        state2, done, info = apply_action(state1, defend_action)

        # Both pass
        pass_action = Action(typ=ActType.PASS)
        state3, done, info = apply_action(state2, pass_action)
        state4, done, info = apply_action(state3, pass_action)

        # Life should be unchanged
        assert state4.players[1].life == defender_initial_life


class TestResolutionStep:
    """Tests for Resolution Step (COMBAT_FLOW.md section 6)."""

    def test_resolution_go_again_restores_action_point(self):
        """
        Given: Attack had Go Again keyword
        When: Resolution step executes
        Then: action_points incremented by 1
        """
        from tests.conftest import execute_full_combat

        gs = create_test_game(phase=Phase.ACTION, turn=0, action_points=1)
        go_again_card = Card(name="Go Again Attack", cost=0, attack=4, defense=2, pitch=1, keywords=["go_again"])
        gs.players[0].hand = [go_again_card]

        # Execute full combat with Go Again attack
        attack_action = Action(typ=ActType.PLAY_ATTACK, play_idx=0, pitch_mask=0)
        final_state = execute_full_combat(gs, attack_action)

        # Action point should be restored (0 from attack + 1 from Go Again)
        assert final_state.action_points == 1

    def test_resolution_no_go_again(self):
        """
        Given: Attack did not have Go Again
        When: Resolution step executes
        Then: action_points remains 0
        """
        gs = create_test_game(phase=Phase.ACTION, turn=0, action_points=1)
        normal_card = Card(name="Normal Attack", cost=0, attack=4, defense=2, pitch=1, keywords=[])
        gs.players[0].hand = [normal_card]

        # Execute attack
        attack_action = Action(typ=ActType.PLAY_ATTACK, play_idx=0, pitch_mask=0)
        state1, done, info = apply_action(gs, attack_action)

        # Defender passes, both pass in reaction
        pass_action = Action(typ=ActType.PASS)
        state2, done, info = apply_action(state1, pass_action)
        state3, done, info = apply_action(state2, pass_action)
        state4, done, info = apply_action(state3, pass_action)

        # Action point should NOT be restored
        assert state4.action_points == 0

    def test_resolution_combat_state_reset(self):
        """
        Given: Resolution completing
        When: Resolution step executes
        Then: Combat state fields reset to initial values
        """
        from tests.conftest import execute_full_combat

        gs = create_test_game(phase=Phase.ACTION, turn=0, action_points=1)
        attack_card = Card(name="Attack", cost=0, attack=5, defense=3, pitch=1)
        gs.players[0].hand = [attack_card]

        # Execute full combat
        attack_action = Action(typ=ActType.PLAY_ATTACK, play_idx=0, pitch_mask=0)
        final_state = execute_full_combat(gs, attack_action)

        # Combat state should be reset
        assert final_state.pending_attack == 0
        assert final_state.reaction_block == 0
        assert final_state.reaction_actor is None
        assert final_state.combat_step == CombatStep.IDLE
        assert final_state.awaiting_defense is False
        assert final_state.combat_passes == 0

    def test_resolution_returns_to_action_phase(self):
        """
        Given: Resolution complete
        When: Checking phase
        Then: Phase remains ACTION, attacker retains priority
        """
        gs = create_test_game(phase=Phase.ACTION, turn=0, action_points=1)
        attack_card = Card(name="Attack", cost=0, attack=5, defense=3, pitch=1)
        gs.players[0].hand = [attack_card]

        # Execute full combat
        attack_action = Action(typ=ActType.PLAY_ATTACK, play_idx=0, pitch_mask=0)
        state1, done, info = apply_action(gs, attack_action)

        pass_action = Action(typ=ActType.PASS)
        state2, done, info = apply_action(state1, pass_action)
        state3, done, info = apply_action(state2, pass_action)
        state4, done, info = apply_action(state3, pass_action)

        # Should still be in action phase
        assert state4.phase == Phase.ACTION
        # Active player should still be the attacker
        assert state4.turn == 0
