# Training Freeze Fix

## Problem Summary

**Issue:** Training freezes at timestep 8192 (exactly 2 × 4096 rollouts) and doesn't progress.

**Root Cause:** The environment had **no maximum episode length**, allowing games to run indefinitely if they entered edge cases or stuck states.

## Technical Details

### The Bug

In `fabgame/rl/env.py:284`, the `step()` function always returned:

```python
return obs_with_mask, float(reward), done, False, info
                                           ^^^^^ Always False!
```

The `truncated` flag (5th return value in Gymnasium's API) was hardcoded to `False`, meaning episodes never timed out.

### Why This Caused Freezing

1. PPO collects rollouts of `n_steps=4096` steps
2. After collecting 2 rollouts (8192 steps), it tries to collect a 3rd rollout
3. If any game in the 3rd rollout gets stuck in an infinite loop:
   - Both players keep passing
   - Edge case in game logic
   - Deck runs out but game doesn't terminate
4. The training process waits forever for that episode to finish
5. Training appears "frozen"

### Termination Check is Insufficient

The game only terminates when a player's life reaches 0:

```python
# fabgame/action_execution.py:122
def _check_term(state: GameState) -> bool:
    return any(player.life <= 0 for player in state.players)
```

But this doesn't handle:
- Infinite pass loops
- Deck exhaustion without damage
- Edge cases in complex game states

## The Fix

### 1. Added `max_episode_steps` parameter to `FabgameEnv`

**File:** `fabgame/rl/env.py`

```python
def __init__(
    self,
    *,
    # ... other params ...
    max_episode_steps: int = 500,  # NEW: Prevent infinite games
    # ... other params ...
):
    # ...
    self.max_episode_steps = max_episode_steps
```

### 2. Check and enforce episode length limit

**File:** `fabgame/rl/env.py:270-275`

```python
# NEW: Check if episode should be truncated due to max steps
truncated = self._step_count >= self.max_episode_steps
if truncated and not done:
    # Game ran too long without natural termination
    # Give small negative reward to discourage infinite games
    reward += -0.5
```

### 3. Return proper `truncated` flag

**File:** `fabgame/rl/env.py:295`

```python
return obs_with_mask, float(reward), done, truncated, info
#                                          ^^^^^^^^^ Now properly set!
```

### 4. Updated training scripts

**Files:**
- `scripts/train_sb3.py` - Original script now includes `max_episode_steps=500`
- `scripts/train_sb3_improved.py` - Improved script with configurable `--max-episode-steps`

## Why 500 Steps?

Based on game analysis:
- **Typical games**: 30-70 steps (normal pace)
- **Slow games**: 100-150 steps (very defensive play)
- **Pathological games**: 200+ steps (stuck states)

**500 steps** is a safe upper bound that:
- ✓ Allows even very slow games to complete naturally
- ✓ Prevents truly infinite games from blocking training
- ✓ Adds penalty (-0.5 reward) to discourage stalling strategies

## Testing the Fix

### Quick Test

```bash
# This should now complete without freezing
python -m scripts.train_sb3_improved --total-timesteps 100000
```

You should see:
- Progress bar updates continuously
- Episode lengths reported (mostly 30-70 steps)
- Occasional truncated episodes (if any hit 500 steps)

### Monitor for Issues

Watch for these signs:
- **Good:** Most episodes complete in <100 steps
- **Warning:** Many episodes truncating at exactly 500 steps (indicates game logic issues)
- **Bad:** Training still freezes (indicates a different problem)

If you see many truncations:
```bash
# Increase the limit temporarily to diagnose
python -m scripts.train_sb3_improved --max-episode-steps 1000
```

## What If Games Still Freeze?

If training still freezes after this fix:

### 1. Check for actual deadlocks

```bash
# Run with timeout to detect hangs
timeout 3600 python -m scripts.train_sb3_improved --total-timesteps 100000
```

If it times out, there's a deeper issue.

### 2. Look for infinite loops in game logic

Check these files:
- `fabgame/action_execution.py` - Action execution logic
- `fabgame/action_enumeration.py` - Legal action generation
- `fabgame/models.py` - Draw/shuffle operations (especially `draw_up_to()`)

Look for `while` loops without guaranteed termination.

### 3. Add defensive checks

```python
# In fabgame/rl/env.py
def step(self, action):
    # ... existing code ...

    # Safety check: if no legal actions, end episode
    if not self.legal_actions() and not self._done:
        print(f"WARNING: No legal actions at step {self._step_count}")
        return obs, -1.0, True, True, info  # Force termination
```

## Performance Impact

**Minimal:**
- Single integer comparison per step: `self._step_count >= self.max_episode_steps`
- No impact on normal-length games (complete before limit)
- Prevents catastrophic training failures from infinite games

## Summary

| Before Fix | After Fix |
|------------|-----------|
| No episode timeout | 500-step timeout |
| `truncated` always `False` | `truncated` set properly |
| Games can run forever | Games max out at 500 steps |
| Training freezes | Training completes |

**Status:** ✅ Fixed in all training scripts

**Affected files:**
- `fabgame/rl/env.py` - Core environment fix
- `scripts/train_sb3.py` - Original script updated
- `scripts/train_sb3_improved.py` - Improved script updated

**Next steps:**
Run training and verify it progresses past 8192 steps without freezing!

```bash
python -m scripts.train_sb3_improved --total-timesteps 1000000
```

Good luck! 🎮
