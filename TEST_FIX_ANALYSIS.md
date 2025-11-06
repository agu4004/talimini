# Test Failure Analysis

## Root Cause Discovered

After detailed investigation, **the implementation is CORRECT**. The test failures are due to tests not properly accounting for the **LAYER step** that occurs after attack declaration.

### What We Found

1. **Go Again mechanism works correctly** (lines 635, 676 in action_execution.py)
   - Flag is set: `self.state.last_attack_had_go_again = card.has_keyword("go_again")`
   - Action points are restored: line 446

2. **Damage application works correctly** (line 441 in action_execution.py)
   - Damage applied: `self.defending_player.life -= damage`

3. **Combat state reset works correctly** (lines 468-479 in action_execution.py)
   - All fields properly cleared

### Why Tests Fail

According to [COMBAT_FLOW.md](COMBAT_FLOW.md), the combat sequence is:

```
Attack Declared → LAYER step → ATTACK step → DEFEND → REACTION → DAMAGE → RESOLUTION
```

**Tests were written as:**
```python
attack_action = Action(typ=ActType.PLAY_ATTACK, ...)
state1 = apply_action(gs, attack_action)

# Immediately try to defend - ILLEGAL!
defend_action = Action(typ=ActType.DEFEND, ...)
state2 = apply_action(state1, defend_action)  # Fails: "Only PASS allowed during layer step"
```

**Correct sequence should be:**
```python
attack_action = Action(typ=ActType.PLAY_ATTACK, ...)
state1 = apply_action(gs, attack_action)  # Now in LAYER step

# Pass through layer step (2 passes required)
pass_action = Action(typ=ActType.PASS)
state2 = apply_action(state1, pass_action)  # Attacker pass
state3 = apply_action(state2, pass_action)  # Defender pass → closes layer

# NOW can defend
defend_action = Action(typ=ActType.DEFEND, ...)
state4 = apply_action(state3, defend_action)  # Success!
```

### Evidence

```
$ python -c "... defend immediately after attack ..."
Info: {'type': 'illegal_action', 'action': 'DEFEND',
       'reason': 'Only PASS is allowed during the layer step',
       'phase': 'ACTION', 'combat_step': 'LAYER'}
```

### Fix Strategy

Create helper functions to abstract combat sequences for tests that don't care about layer step details:

1. `execute_attack_through_layer()` - Attack + layer passes
2. `execute_full_combat()` - Full attack → defend → reaction → resolution
3. `skip_layer_step()` - Just the two passes
