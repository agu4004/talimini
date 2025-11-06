# Comprehensive Test Plan for Game Flow & Combat Flow

This document outlines a thorough test suite to verify that the implementation matches the specifications in [GAME_FLOW.md](GAME_FLOW.md) and [COMBAT_FLOW.md](COMBAT_FLOW.md).

---

## Test Categories

1. [Turn Phase Tests](#1-turn-phase-tests) - Verify phase transitions and state management
2. [Combat Flow Tests](#2-combat-flow-tests) - Verify all 6 combat steps
3. [Action Type Tests](#3-action-type-tests) - Verify all action types work correctly
4. [State Management Tests](#4-state-management-tests) - Verify state fields are updated correctly
5. [Event Logging Tests](#5-event-logging-tests) - Verify events match documentation
6. [Edge Case Tests](#6-edge-case-tests) - Verify corner cases and error handling
7. [Integration Tests](#7-integration-tests) - End-to-end game scenarios

---

## 1. Turn Phase Tests

### 1.1 Start Phase Tests

**Test: `test_start_phase_initialization`**
- Given: Previous turn ended with `_end_and_pass_turn`
- When: Start phase begins
- Then:
  - Active player draws up to intellect
  - `floating_resources` reset to [0, 0]
  - Only legal action is `CONTINUE`
  - Phase is `Phase.SOT`

**Test: `test_start_phase_continue_grants_action_point`**
- Given: Player at start phase
- When: Player executes `CONTINUE` action
- Then:
  - `action_points` set to 1
  - Phase transitions to `Phase.ACTION`
  - `combat_step` is `CombatStep.IDLE`

**Test: `test_start_phase_draw_up_to_intellect`**
- Given: Player with 2 cards in hand, 10 cards in deck
- When: Start phase draws cards
- Then:
  - Hand size equals `INTELLECT` (from config)
  - Cards moved from deck to hand
  - Draw order is from top of deck (last element)

### 1.2 Action Phase Tests

**Test: `test_action_phase_legal_actions_no_combat`**
- Given: Player in action phase with no pending combat
- When: `enumerate_legal_actions` is called
- Then:
  - Can play attacks from hand (`PLAY_ATTACK`)
  - Can play arsenal attacks if arsenal not empty (`PLAY_ARSENAL_ATTACK`)
  - Can use weapon attack if weapon available and not used (`WEAPON_ATTACK`)
  - Can `PASS` to end turn

**Test: `test_action_phase_consumes_action_point`**
- Given: Player has 1 action point
- When: Player plays an attack
- Then:
  - `action_points` decremented to 0
  - Combat sequence initiated

**Test: `test_action_phase_pass_no_combat_enters_end_phase`**
- Given: Player in action phase, no combat pending, action points remaining
- When: Player executes `PASS`
- Then:
  - Phase transitions to `Phase.END`
  - `awaiting_arsenal` becomes True
  - `arsenal_player` set to current player

### 1.3 End Phase Tests

**Test: `test_end_phase_arsenal_setting`**
- Given: Player in end phase with cards in hand
- When: `enumerate_legal_actions` is called
- Then:
  - Can `SET_ARSENAL` for each card in hand (if arsenal slot empty)
  - Can `PASS` to skip arsenal setting

**Test: `test_end_phase_set_arsenal_moves_card`**
- Given: Player in end phase
- When: Player executes `SET_ARSENAL` with card index
- Then:
  - Card moved from hand to arsenal
  - `awaiting_arsenal` becomes False
  - Turn passing sequence begins

**Test: `test_end_phase_turn_transition`**
- Given: Player completes arsenal step (or passes)
- When: `_end_and_pass_turn` executes
- Then:
  - Pitched cards moved to bottom of deck
  - Player draws up to intellect
  - `floating_resources` cleared to [0, 0]
  - Reaction metadata cleared (`reaction_actor`, `reaction_block`, `reaction_arsenal_cards`)
  - Weapon `used_this_turn` flags reset
  - `turn` incremented or toggled
  - Phase returns to `Phase.SOT`
  - Next player becomes active

---

## 2. Combat Flow Tests

### 2.1 Layer Step Tests

**Test: `test_layer_step_initialization`**
- Given: Attack just declared
- When: Combat begins
- Then:
  - `combat_step` is `CombatStep.LAYER`
  - `combat_priority` set to attacker index
  - `combat_passes` is 0
  - Only legal action is `PASS`

**Test: `test_layer_step_priority_toggle`**
- Given: Layer step with attacker having priority
- When: Attacker executes `PASS`
- Then:
  - `combat_priority` toggles to defender
  - `combat_passes` incremented to 1

**Test: `test_layer_step_closes_after_two_passes`**
- Given: Layer step with 1 pass already recorded
- When: Second player executes `PASS`
- Then:
  - `layer_end` event logged
  - `combat_step` transitions to `CombatStep.ATTACK`
  - `awaiting_defense` becomes True

**Test: `test_layer_step_priority_returns_on_action`**
- Given: Layer step (future: if instant effects allowed)
- When: Player plays an instant
- Then:
  - `combat_passes` resets to 0
  - Priority returns to opponent

### 2.2 Attack Step Tests

**Test: `test_attack_step_cost_payment`**
- Given: Player attacks with card costing 3, has 1 floating resource
- When: Attack executes
- Then:
  - `_consume_resources` called with cost 3
  - Uses floating resource first
  - Pitches cards totaling 2+ pitch value
  - Pitched cards moved to `pitched` list
  - `last_pitch_sum` updated

**Test: `test_attack_step_card_movement`**
- Given: Player plays attack from hand
- When: Attack step executes
- Then:
  - Attack card moved from hand to graveyard
  - Weapon attacks: weapon stays equipped, `used_this_turn` set to True

**Test: `test_attack_step_modifier_application`**
- Given: Player is Ira, making second attack this turn
- When: `apply_on_declare_attack_modifiers` called
- Then:
  - `pending_attack` set to base attack + modifiers (+1 for Ira)
  - `last_attack_card` stored
  - `last_attack_had_go_again` set based on Go Again keyword
  - Hero-specific modifiers applied (from `hero_modifiers` YAML)

**Test: `test_attack_step_combat_state_prep`**
- Given: Attack modifiers applied
- When: Attack step completes
- Then:
  - `combat_step` set to `CombatStep.ATTACK`
  - `awaiting_defense` is True
  - `reaction_actor` set to defender
  - Reaction trackers reset

**Test: `test_attack_step_declare_event`**
- Given: Attack declared
- When: Attack step executes
- Then:
  - `declare_attack` event emitted
  - Event contains: card name, final attack, cost, pitch used, source (hand/arsenal/weapon)

### 2.3 Defend Step Tests

**Test: `test_defend_step_legal_actions`**
- Given: Defender in defend step
- When: `enumerate_legal_actions` called
- Then:
  - Can `DEFEND` with combinations of up to `DEFEND_MAX` non-reaction cards
  - Can `PASS` to block with 0 cards
  - Reaction cards NOT included in defend step

**Test: `test_defend_step_block_cards_movement`**
- Given: Defender chooses to block with 2 cards
- When: `DEFEND` action executes
- Then:
  - Selected cards moved from hand to graveyard
  - Defense values summed into `reaction_block`
  - `block_play` event emitted

**Test: `test_defend_step_pass_no_block`**
- Given: Defender in defend step
- When: Defender executes `PASS`
- Then:
  - `reaction_block` remains 0
  - `block_pass` event emitted
  - Transitions to reaction step

**Test: `test_defend_step_transition_to_reaction`**
- Given: Defender completes block declaration
- When: Defend step completes
- Then:
  - `combat_step` set to `CombatStep.REACTION`
  - `reaction_actor` set to defender (defender has first reaction priority)
  - `combat_passes` reset to 0

### 2.4 Reaction Step Tests

**Test: `test_reaction_step_defender_priority_defense_reaction`**
- Given: Defender has priority in reaction step, has defense reaction in hand
- When: `enumerate_legal_actions` called
- Then:
  - Can `DEFEND` with defense reaction cards
  - Can `PASS`
  - Cannot play attack reactions

**Test: `test_reaction_step_defender_plays_defense_reaction`**
- Given: Defender plays defense reaction
- When: `DEFEND` action executes
- Then:
  - Reaction card moved from hand/arsenal to graveyard
  - Defense value added to `reaction_block`
  - If from arsenal: added to `reaction_arsenal_cards`
  - `defense_react_play` event emitted
  - `combat_passes` reset to 0
  - Priority returns to defender (defender keeps priority after defense reaction)

**Test: `test_reaction_step_defender_pass`**
- Given: Defender has priority, chooses not to react
- When: Defender executes `PASS`
- Then:
  - `combat_passes` set to 1
  - `reaction_actor` toggles to attacker
  - `reaction_pass` event emitted

**Test: `test_reaction_step_attacker_priority_attack_reaction`**
- Given: Attacker has priority, has attack reaction in hand
- When: `enumerate_legal_actions` called
- Then:
  - Can `PLAY_ATTACK_REACTION` with attack reaction cards
  - Can `PASS`
  - Cannot play defense reactions

**Test: `test_reaction_step_attacker_plays_attack_reaction`**
- Given: Attacker plays attack reaction
- When: `PLAY_ATTACK_REACTION` executes
- Then:
  - Resources consumed (floating + pitch)
  - Reaction card moved to graveyard
  - Attack bonus added to `pending_attack`
  - `attack_react` event emitted
  - `combat_passes` reset to 0
  - `reaction_actor` toggles to defender

**Test: `test_reaction_step_attacker_pass_with_zero_passes`**
- Given: Attacker has priority, `combat_passes` is 0
- When: Attacker executes `PASS`
- Then:
  - Priority returns to defender
  - `reaction_actor` toggles to defender
  - `combat_passes` remains 0 (or increments depending on implementation)

**Test: `test_reaction_step_closes_after_consecutive_passes`**
- Given: Defender passed (combat_passes = 1), attacker has priority
- When: Attacker executes `PASS`
- Then:
  - Reaction step closes
  - Transitions to damage calculation
  - `combat_step` becomes `CombatStep.DAMAGE`

### 2.5 Damage Step Tests

**Test: `test_damage_calculation`**
- Given: `pending_attack` is 7, `reaction_block` is 3
- When: Damage step executes
- Then:
  - `pending_damage` calculated as max(0, 7 - 3) = 4
  - Damage applied to defender's life
  - Defender life reduced by 4

**Test: `test_damage_zero_when_block_exceeds_attack`**
- Given: `pending_attack` is 5, `reaction_block` is 8
- When: Damage step executes
- Then:
  - `pending_damage` is 0
  - Defender life unchanged

**Test: `test_damage_step_transitions`**
- Given: Damage calculated
- When: Damage step completes
- Then:
  - `combat_step` set to `CombatStep.DAMAGE` then `CombatStep.RESOLUTION`
  - No further actions offered
  - Proceeds directly to resolution

**Test: `test_damage_marks_hit`**
- Given: Attack dealt damage > 0
- When: Damage applied
- Then:
  - Attack considered to have "hit"
  - (Future: triggers "on hit" effects)

### 2.6 Resolution Step Tests

**Test: `test_resolution_event_logging`**
- Given: Combat resolving
- When: Resolution step executes
- Then:
  - `defense_resolve` event logged
  - Event contains: total block, damage dealt, remaining life, arsenal reactions list

**Test: `test_resolution_go_again_restores_action_point`**
- Given: Attack had Go Again keyword, `last_attack_had_go_again` is True
- When: Resolution step executes
- Then:
  - `action_points` incremented by 1
  - Attacker can continue attacking

**Test: `test_resolution_no_go_again`**
- Given: Attack did not have Go Again
- When: Resolution step executes
- Then:
  - `action_points` remains 0
  - Attacker cannot make another attack

**Test: `test_resolution_combat_state_reset`**
- Given: Resolution completing
- When: Resolution step executes
- Then:
  - `pending_attack` reset to 0
  - `reaction_block` reset to 0
  - `reaction_actor` reset to None
  - `reaction_arsenal_cards` cleared
  - `combat_step` reset to `CombatStep.IDLE`
  - `combat_priority` reset to None
  - `combat_passes` reset to 0
  - `awaiting_defense` reset to False

**Test: `test_resolution_returns_to_action_phase`**
- Given: Resolution complete
- When: Checking phase
- Then:
  - Phase remains `Phase.ACTION`
  - Attacker retains priority
  - Can spend remaining action points or pass

---

## 3. Action Type Tests

### 3.1 CONTINUE Action

**Test: `test_continue_only_legal_at_start`**
- Given: Game at start of turn phase
- When: Checking legal actions
- Then: Only `CONTINUE` available

**Test: `test_continue_grants_action_point_and_transitions`**
- Covered in section 1.1

### 3.2 PLAY_ATTACK Action

**Test: `test_play_attack_from_hand_basic`**
- Given: Player has attack card in hand, sufficient resources
- When: `PLAY_ATTACK` executed
- Then:
  - Cost paid via floating + pitch
  - Card moved to graveyard
  - Attack value recorded in `pending_attack`
  - Combat sequence initiated

**Test: `test_play_attack_insufficient_resources`**
- Given: Player has expensive card, insufficient pitch pool
- When: Checking legal actions
- Then:
  - Card not in legal action list
  - Or action fails if attempted

### 3.3 PLAY_ARSENAL_ATTACK Action

**Test: `test_arsenal_attack_basic`**
- Given: Player has attack card in arsenal
- When: `PLAY_ARSENAL_ATTACK` executed
- Then:
  - Card moved from arsenal to graveyard
  - Costs paid (arsenal cards can still have costs)
  - Combat initiated

### 3.4 WEAPON_ATTACK Action

**Test: `test_weapon_attack_basic`**
- Given: Player has weapon equipped, not used this turn
- When: `WEAPON_ATTACK` executed
- Then:
  - Weapon attack value becomes `pending_attack`
  - Cost paid
  - `weapon.used_this_turn` set to True
  - Weapon stays equipped (not moved to graveyard)

**Test: `test_weapon_attack_once_per_turn_restriction`**
- Given: Weapon with `once_per_turn=True`, already used
- When: Checking legal actions
- Then:
  - `WEAPON_ATTACK` not available

**Test: `test_weapon_attack_go_again`**
- Given: Weapon with Go Again keyword
- When: Weapon attack resolves
- Then:
  - Action point restored
  - Can attack again

### 3.5 DEFEND Action

**Test: `test_defend_in_block_phase`**
- Covered in section 2.3

**Test: `test_defend_with_defense_reactions`**
- Covered in section 2.4

**Test: `test_defend_mask_encoding`**
- Given: Defender selecting multiple block cards
- When: Action created
- Then:
  - `defend_mask` correctly encodes selected cards as bitmask
  - Correct cards identified from mask

### 3.6 PLAY_ATTACK_REACTION Action

**Test: `test_attack_reaction_during_reaction_step`**
- Covered in section 2.4

**Test: `test_attack_reaction_cost_payment`**
- Given: Attack reaction with cost
- When: `PLAY_ATTACK_REACTION` executed
- Then:
  - Resources consumed via floating + pitch
  - Pitch cards moved to `pitched` list

### 3.7 PASS Action

**Test: `test_pass_in_action_phase_ends_turn`**
- Covered in section 1.2

**Test: `test_pass_in_layer_step`**
- Covered in section 2.1

**Test: `test_pass_in_reaction_step`**
- Covered in section 2.4

**Test: `test_pass_in_end_phase`**
- Given: End phase arsenal prompt
- When: `PASS` executed
- Then:
  - No arsenal set
  - Turn passing continues

### 3.8 SET_ARSENAL Action

**Test: `test_set_arsenal_moves_card`**
- Covered in section 1.3

**Test: `test_set_arsenal_only_if_slot_empty`**
- Given: Arsenal already occupied
- When: Checking legal actions in end phase
- Then:
  - `SET_ARSENAL` not available

---

## 4. State Management Tests

### 4.1 Combat State Fields

**Test: `test_combat_step_progression`**
- Given: Full combat sequence
- When: Tracking `combat_step`
- Then:
  - Progresses: IDLE → LAYER → ATTACK → REACTION → DAMAGE → RESOLUTION → IDLE

**Test: `test_combat_priority_toggle`**
- Given: Layer step
- When: Players pass
- Then:
  - `combat_priority` alternates between attacker and defender

**Test: `test_combat_passes_tracking`**
- Given: Reaction step
- When: Players pass
- Then:
  - `combat_passes` increments correctly
  - Resets to 0 when action taken

**Test: `test_pending_attack_accumulation`**
- Given: Base attack 5, attack reaction adds 3
- When: Tracking `pending_attack`
- Then:
  - Starts at 5 after declare
  - Becomes 8 after reaction

**Test: `test_reaction_block_accumulation`**
- Given: Block with 2 defense, then defense reaction with 3 defense
- When: Tracking `reaction_block`
- Then:
  - Starts at 2 after block
  - Becomes 5 after reaction

**Test: `test_reaction_actor_toggle`**
- Given: Reaction step
- When: Players take actions or pass
- Then:
  - `reaction_actor` alternates between defender and attacker

### 4.2 Resource Management

**Test: `test_floating_resources_persistence`**
- Given: Player pitches 3 resources but only spends 2
- When: Tracking `floating_resources`
- Then:
  - 1 resource remains floating
  - Available for next action in same turn

**Test: `test_floating_resources_used_first`**
- Given: Player has 2 floating, plays card costing 3
- When: `_consume_resources` called
- Then:
  - Uses 2 floating first
  - Pitches only 1 additional

**Test: `test_floating_resources_reset_end_of_turn`**
- Given: Player has floating resources
- When: `_end_and_pass_turn` executes
- Then:
  - `floating_resources` reset to [0, 0]

### 4.3 Card Zone Tracking

**Test: `test_pitched_cards_bottom_deck`**
- Given: Player pitched 3 cards this turn
- When: `_end_and_pass_turn` executes
- Then:
  - All 3 cards moved from `pitched` to bottom of `deck`
  - Order preserved (bottom-most first)

**Test: `test_graveyard_accumulation`**
- Given: Multiple attacks and blocks
- When: Cards used
- Then:
  - All non-pitched cards move to `grave`
  - Graveyard order preserved

**Test: `test_arsenal_persistence`**
- Given: Card set to arsenal
- When: Turn passes
- Then:
  - Card remains in arsenal
  - Can be used in future turn

### 4.4 Action Points

**Test: `test_action_points_start_at_one`**
- Given: Start phase CONTINUE executed
- When: Entering action phase
- Then: `action_points` is 1

**Test: `test_action_points_decremented_on_attack`**
- Given: Player has 1 action point
- When: Attack played
- Then: `action_points` becomes 0

**Test: `test_action_points_restored_by_go_again`**
- Given: Attack with Go Again resolves
- When: Resolution step completes
- Then: `action_points` incremented by 1

---

## 5. Event Logging Tests

Verify that each documented event is emitted with correct data at the right time.

**Test: `test_layer_pass_event`**
- When: Player passes in layer step
- Then: `layer_pass` event logged with player index

**Test: `test_layer_end_event`**
- When: Layer closes after two passes
- Then: `layer_end` event logged

**Test: `test_declare_attack_event`**
- When: Attack declared
- Then: `declare_attack` event with card name, attack, cost, pitch, source

**Test: `test_block_play_event`**
- When: Defender declares block
- Then: `block_play` event with block cards and total

**Test: `test_block_pass_event`**
- When: Defender passes on block
- Then: `block_pass` event logged

**Test: `test_defense_react_play_event`**
- When: Defense reaction played
- Then: `defense_react_play` event with card name and defense value

**Test: `test_attack_react_event`**
- When: Attack reaction played
- Then: `attack_react` event with card name and attack bonus

**Test: `test_reaction_pass_event`**
- When: Player passes in reaction step
- Then: `reaction_pass` event with player index

**Test: `test_defense_resolve_event`**
- When: Combat resolves
- Then: `defense_resolve` event with block total, damage, remaining life, arsenal reactions

---

## 6. Edge Case Tests

### 6.1 Resource Edge Cases

**Test: `test_exact_resource_payment`**
- Given: Card costs 3, player has exactly 3 pitch
- When: Attack played
- Then: All resources consumed, attack succeeds

**Test: `test_zero_cost_attack`**
- Given: Card with cost 0
- When: Attack played
- Then: No pitching required, attack succeeds

**Test: `test_over_pitching_creates_floating`**
- Given: Card costs 2, player pitches 3
- When: Attack played
- Then: 1 resource remains floating

### 6.2 Combat Edge Cases

**Test: `test_attack_with_zero_damage`**
- Given: Attack value equals block value
- When: Damage calculated
- Then: `pending_damage` is 0, life unchanged

**Test: `test_attack_kills_defender`**
- Given: Defender at 3 life, attack deals 5 damage
- When: Damage applied
- Then:
  - Defender life becomes -2 (or 0, depending on rules)
  - Game ends, attacker wins

**Test: `test_empty_hand_defense`**
- Given: Defender has no cards in hand
- When: Defend step
- Then: Only option is `PASS`, block total is 0

**Test: `test_all_cards_are_reactions`**
- Given: Defender hand contains only reaction cards
- When: Defend step (non-reaction block)
- Then: Cannot block with reactions, must pass

### 6.3 Special Scenarios

**Test: `test_multiple_go_again_attacks`**
- Given: Player has multiple Go Again attacks
- When: Attacks resolve sequentially
- Then:
  - Each restores action point
  - Player can chain attacks

**Test: `test_weapon_used_flag_reset`**
- Given: Weapon used in turn 1
- When: Turn passes to turn 2
- Then: `weapon.used_this_turn` reset to False

**Test: `test_second_attack_hero_modifier`**
- Given: Hero is Ira (bonus on second attack)
- When: Second attack declared
- Then: Attack bonus applied (+1)

**Test: `test_arsenal_defense_reaction_tracking`**
- Given: Defense reaction played from arsenal
- When: Reaction resolves
- Then:
  - Added to `reaction_arsenal_cards` list
  - Included in `defense_resolve` event

### 6.4 Boundary Cases

**Test: `test_max_defend_limit`**
- Given: `DEFEND_MAX` is 2, player has 5 cards
- When: Checking legal block actions
- Then: Can select up to 2 cards, not more

**Test: `test_empty_deck_no_draw`**
- Given: Player deck is empty
- When: Start phase draw
- Then: Draws 0 cards, no error

**Test: `test_intellect_zero`**
- Given: Hero with 0 intellect (if possible)
- When: Start phase draw
- Then: Draws 0 cards

---

## 7. Integration Tests

Full end-to-end scenarios testing complete game flows.

**Test: `test_full_turn_sequence_basic`**
- Given: Game initialized
- When: Complete turn sequence executed
- Then:
  1. Start: CONTINUE → action phase
  2. Action: Play attack → combat sequence
  3. Combat: Layer → Attack → Defend → Reaction → Damage → Resolution
  4. Action: PASS → end phase
  5. End: SET_ARSENAL → next turn

**Test: `test_multi_attack_turn_with_go_again`**
- Given: Player has 2 Go Again attacks
- When: Turn executed
- Then:
  1. First attack → Go Again restores action point
  2. Second attack → No more action points
  3. PASS → end phase

**Test: `test_combat_with_defense_reactions`**
- Given: Defender has defense reactions
- When: Combat executed
- Then:
  1. Block declared
  2. Defense reaction played
  3. Block total accumulates
  4. Damage reduced accordingly

**Test: `test_combat_with_attack_reactions`**
- Given: Attacker has attack reactions
- When: Combat executed
- Then:
  1. Initial attack declared
  2. Defense declared
  3. Attack reaction played
  4. Attack value increased
  5. Damage calculated with new total

**Test: `test_reaction_priority_alternation`**
- Given: Both players have reactions
- When: Reaction step executes
- Then:
  1. Defender reacts → priority to attacker
  2. Attacker reacts → priority to defender
  3. Defender passes → priority to attacker
  4. Attacker passes → resolve

**Test: `test_game_to_completion`**
- Given: Two players, full decks
- When: Game played until win condition
- Then:
  - Multiple turns execute correctly
  - Life totals decrease
  - One player reaches 0 life
  - Winner declared

---

## Test Implementation Strategy

### Phase 1: Unit Tests (Priority: HIGH)
- Implement sections 1, 2, 3, 4
- Focus on state transitions and field updates
- Mock out event logging if needed

### Phase 2: Event Tests (Priority: MEDIUM)
- Implement section 5
- Verify events match documentation
- Use event capture/spy mechanisms

### Phase 3: Edge Cases (Priority: MEDIUM)
- Implement section 6
- Test boundary conditions
- Test error handling

### Phase 4: Integration Tests (Priority: HIGH)
- Implement section 7
- End-to-end scenarios
- Regression prevention

### Test Utilities Needed

**Helper Functions:**
- `create_test_game_state()` - Initialize test states
- `create_test_card()` - Create cards with specific properties
- `create_test_weapon()` - Create weapons
- `simulate_attack_sequence()` - Execute full attack
- `capture_events()` - Capture event log
- `assert_state_equals()` - Deep state comparison

**Fixtures:**
- Common game states (start of turn, mid-combat, etc.)
- Card libraries (attacks, defenses, reactions)
- Hero configurations

---

## Coverage Goals

- **Line Coverage**: >90%
- **Branch Coverage**: >85%
- **State Transitions**: 100% (all phase and combat step transitions)
- **Action Types**: 100% (all ActType enum values)
- **Event Types**: 100% (all documented events)

---

## Documentation Compliance Matrix

| Requirement | Test(s) | Status |
|-------------|---------|--------|
| Start phase draws to intellect | `test_start_phase_draw_up_to_intellect` | ⬜ Not Implemented |
| CONTINUE grants 1 action point | `test_start_phase_continue_grants_action_point` | ⬜ Not Implemented |
| Layer step priority toggle | `test_layer_step_priority_toggle` | ⬜ Not Implemented |
| Layer closes on 2 passes | `test_layer_step_closes_after_two_passes` | ⬜ Not Implemented |
| Attack pays costs | `test_attack_step_cost_payment` | ⬜ Not Implemented |
| Attack applies modifiers | `test_attack_step_modifier_application` | ⬜ Not Implemented |
| Defend step up to DEFEND_MAX | `test_defend_step_legal_actions` | ⬜ Not Implemented |
| Reaction priority alternates | `test_reaction_step_*` | ⬜ Not Implemented |
| Damage = attack - block | `test_damage_calculation` | ⬜ Not Implemented |
| Go Again restores action point | `test_resolution_go_again_restores_action_point` | ⬜ Not Implemented |
| Combat state resets | `test_resolution_combat_state_reset` | ⬜ Not Implemented |
| End phase arsenal setting | `test_end_phase_arsenal_setting` | ⬜ Not Implemented |
| Turn passes correctly | `test_end_phase_turn_transition` | ⬜ Not Implemented |
| Floating resources persist | `test_floating_resources_persistence` | ⬜ Not Implemented |
| Pitched cards bottom deck | `test_pitched_cards_bottom_deck` | ⬜ Not Implemented |
| All events logged | Section 5 tests | ⬜ Not Implemented |

---

## Next Steps

1. **Review this test plan** with the team
2. **Set up test infrastructure** (pytest, fixtures, helpers)
3. **Implement Phase 1** (unit tests) - highest priority
4. **Run tests and identify discrepancies** between code and documentation
5. **Fix bugs or update documentation** based on findings
6. **Implement remaining phases** (events, edge cases, integration)
7. **Achieve coverage goals**
8. **Set up CI/CD** to run tests on every commit

---

This test plan provides a comprehensive roadmap for verifying that the implementation matches the documented specifications. Each test case is designed to be specific, measurable, and directly tied to the requirements in GAME_FLOW.md and COMBAT_FLOW.md.
