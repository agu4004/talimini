# ML Training Analysis & Improvement Recommendations

## Executive Summary

Your ML agent is underperforming against the heuristic bot due to several key issues:

1. **Sparse rewards** - Win/loss signals too far apart for effective learning
2. **Huge action space** - Thousands of possible actions make exploration difficult
3. **Strong baseline** - Heuristic bot uses sophisticated decision rules
4. **Insufficient training** - 100k timesteps is too few for this complexity
5. **No exploration bonus** - Zero entropy coefficient prevents trying new strategies

## Detailed Problem Analysis

### 1. Reward Structure Issues

**Current Rewards (from `train_sb3.py:120-123`):**
```python
reward_step=-0.01      # Tiny step penalty
reward_on_hit=0.2      # Small bonus for landing damage
reward_good_block=0    # No reward for blocking well
reward_overpitch=0     # No penalty for wasting resources
```

**Problems:**
- **Extremely sparse**: Primary signal is +1/-1 at game end (often 50+ steps away)
- **Weak intermediate rewards**: 0.2 for hitting is dwarfed by the 1.0 win reward
- **No resource management feedback**: Agent doesn't learn to avoid overpitching
- **No defensive skill rewards**: No incentive to block efficiently

**Impact:** Agent gets almost no feedback during the game, making credit assignment nearly impossible. It's like teaching someone chess by only saying "you won" or "you lost" at the end without explaining why.

### 2. Action Space Explosion

**Current Configuration (from `action_mask.py:124`):**
```python
ACTION_VOCAB = ActionVocabulary(max_hand_size=10, max_arsenal_size=4)
```

**Action Space Breakdown:**
- **Pitch masks**: 2^10 = 1,024 combinations (which cards to pitch)
- **Defend masks**: C(10,1) + C(10,2) = 55 combinations
- **Play actions**: 10 hand cards × 1,024 pitch masks = 10,240 options
- **Arsenal attacks**: 4 slots × 1,024 pitch masks = 4,096 options
- **Attack reactions**: (10 hand + 4 arsenal) × 1,024 pitch masks = 14,336 options
- **Total vocabulary size**: **~30,000+ discrete actions**

**Problems:**
- PPO needs to explore this massive space to find good policies
- With sparse rewards, most explorations give no feedback
- Action masking helps but doesn't solve the fundamental exploration problem

### 3. Heuristic Bot Strength

The heuristic bot (from `heuristic.py`) implements sophisticated strategies:

**Arsenal Phase (`_choose_arsenal_action`):**
- Always picks card with highest attack value

**Defense Phase (`_choose_defense_action`):**
- Calculates exact damage incoming
- Blocks **just enough** to survive (minimizes overkill/waste)
- If can't block lethal, uses maximum available defense

**Attack Phase (`_choose_attack_action`):**
- Scores attacks by: `(cost, overpitch, -attack, type_bias)`
- Minimizes resource waste (overpitch)
- Maximizes damage output
- Considers weapon attacks vs card attacks

**Reaction Phase (`_choose_reaction_action`):**
- Maximizes attack bonus from reactions
- Minimizes cost and overpitch

**Why This Matters:**
This isn't a random baseline - it's a near-optimal greedy strategy! Your ML agent needs to discover these same strategies through trial and error with minimal feedback signals.

### 4. Training Configuration Issues

**Current Training (from `train_sb3.py:68-76`):**
```python
--total-timesteps 100000    # Too few for this complexity
--learning-rate 3e-4        # Standard
--n-steps 2048              # Reasonable
--batch-size 64             # Small given action space
--n-epochs 10               # Standard
--ent-coef 0.0              # NO EXPLORATION BONUS ⚠️
--gamma 0.99                # Standard discount
```

**Problems:**
- **100k timesteps ≈ 2,000 games**: Not enough to explore action space
- **Zero entropy coefficient**: No exploration bonus means agent exploits early, possibly suboptimal strategies
- **Small batch size**: Only 64 samples per update with 30k action space
- **No curriculum**: Starts with full game complexity immediately

### 5. Observation Space Complexity

**State Encoding (from `encoding.py`):**
The observation includes:
- Player life, resources, action points
- Hand cards (2 players × 6 cards × 103 features = 1,236 dims)
- Arsenal (2 × 2 × 103 = 412 dims)
- Pitched pile (2 × 8 × 103 = 1,648 dims)
- Graveyard (2 × 8 × 103 = 1,648 dims)
- Phase, combat step, hero encoding
- Combat state (pending attack, damage, etc.)

**Total: ~5,000+ input dimensions**

This is fine for neural networks, but combined with huge action space and sparse rewards, learning becomes very difficult.

---

## Recommended Solutions (Priority Order)

### 🔥 HIGH PRIORITY - Quick Wins

#### 1. **Dramatically Improve Reward Shaping**

**Current:**
```python
reward_step=-0.01
reward_on_hit=0.2
reward_good_block=0
reward_overpitch=0
```

**Recommended:**
```python
# In train_sb3.py:120-123
reward_step=-0.005          # Smaller step penalty (encourage longer games early)
reward_on_hit=0.5           # Bigger bonus for dealing damage
reward_good_block=0.3       # NEW: Reward blocking efficiently
reward_overpitch=-0.2       # NEW: Penalize wasting resources
```

**Additional Reward Signals to Add:**

Add to `FabgameEnv.step()` in `env.py:234-254`:

```python
# Life differential reward (staying alive is good!)
life_delta = next_state.players[actor].life - self.state.players[actor].life
reward += life_delta * 0.01

# Efficient attack reward (attack - cost)
if events and "attack_value" in events and "card_cost" in events:
    attack_efficiency = events["attack_value"] - events["card_cost"]
    if attack_efficiency > 0:
        reward += attack_efficiency * 0.05

# Arsenal usage reward (using cards effectively)
if events and "played_from_arsenal" in events:
    reward += 0.1
```

**Why This Helps:** Gives the agent frequent, meaningful feedback during the game instead of waiting for the end.

---

#### 2. **Add Exploration Bonus (Entropy Coefficient)**

**Current:**
```python
--ent-coef 0.0  # No exploration!
```

**Recommended:**
```python
--ent-coef 0.01  # Start with 1% entropy bonus
```

Or better, use entropy annealing:
```python
# In train_sb3.py, modify to use LinearSchedule
from stable_baselines3.common.utils import LinearSchedule

ent_coef = LinearSchedule(
    initial_p=0.05,   # Start with 5% exploration
    final_p=0.001,    # Decay to 0.1% exploration
    schedule_timesteps=total_timesteps * 0.7
)
```

**Why This Helps:** Without entropy bonus, PPO exploits whatever strategy it finds first (often suboptimal). Entropy encourages trying diverse actions.

---

#### 3. **Increase Training Duration Significantly**

**Current:**
```bash
--total-timesteps 100000  # ~2,000 games
```

**Recommended:**
```bash
--total-timesteps 1000000  # 10x more = ~20,000 games
# Or even better:
--total-timesteps 5000000  # 100,000 games for strong performance
```

**Why This Helps:** Complex action spaces need extensive exploration. Heuristic bot was hand-crafted with domain knowledge; ML needs trial and error.

---

#### 4. **Increase Batch Size and Learning Steps**

**Current:**
```python
--batch-size 64
--n-steps 2048
```

**Recommended:**
```python
--batch-size 256      # 4x larger batches
--n-steps 4096        # More experience per update
```

**Why This Helps:** Larger batches give more stable gradient estimates with huge action spaces.

---

### 🎯 MEDIUM PRIORITY - Architectural Improvements

#### 5. **Implement Curriculum Learning**

Start with easier opponents and gradually increase difficulty:

**Phase 1: Learn Basic Mechanics (100k steps)**
- Opponent: Heavily weakened heuristic (random 30% of the time)
- Reward: Extra bonuses for basic actions (playing attacks, blocking)
- Focus: Learn legal actions and game flow

**Phase 2: Learn Strategy (400k steps)**
- Opponent: Normal heuristic bot
- Reward: Full reward shaping from recommendation #1
- Focus: Learn to compete with strong baseline

**Phase 3: Self-Play Mastery (500k+ steps)**
- Opponent: Mix of heuristic (30%) and self-play (70%)
- Reward: Win/loss focused (reduce shaping)
- Focus: Discover novel strategies beyond heuristic

**Implementation:**
Create `train_sb3_curriculum.py` with phased training loop that adjusts opponent and rewards over time.

---

#### 6. **Reduce Action Space with Simplified Vocabulary**

**Current:**
```python
ACTION_VOCAB = ActionVocabulary(max_hand_size=10, max_arsenal_size=4)
```

**Recommended for Initial Training:**
```python
# Create simpler vocab for early training
SIMPLE_VOCAB = ActionVocabulary(max_hand_size=6, max_arsenal_size=2)
```

**Or use Heuristic-Guided Pitch Selection:**
```python
# Instead of exposing all 1024 pitch masks, expose only:
# - "minimum pitch to afford this card"
# - "pitch all but one"
# - "pitch all"
# This reduces actions from 10,240 to ~30 per card
```

**Why This Helps:** Smaller action space = faster exploration = quicker learning of basics.

---

#### 7. **Use Imitation Learning (Behavioral Cloning) for Warm Start**

The codebase already has self-play data generation (`gen_selfplay_data.py`)!

**Recommended Workflow:**

**Step 1: Generate Heuristic Data**
```bash
# Generate 10,000 games of heuristic vs heuristic
python -m scripts.gen_selfplay_data --episodes 10000 \
    --agent heuristic --output data/heuristic_games.npz
```

**Step 2: Pre-train with Imitation**
```python
# Create new script: train_bc.py
# Train supervised model to predict heuristic actions
# Use cross-entropy loss on action distribution
# Train for 10-20 epochs on the dataset
```

**Step 3: Fine-tune with RL**
```bash
# Load pre-trained model and continue with PPO
python -m scripts.train_sb3 --load-pretrained data/bc_model.zip \
    --total-timesteps 1000000
```

**Why This Helps:** Agent starts with heuristic-level competence, then RL improves from there. Much faster than learning from scratch!

---

### 📊 LOW PRIORITY - Advanced Techniques

#### 8. **Implement Population-Based Training**

Train multiple agents simultaneously with different hyperparameters:
- 5 agents with different learning rates: [1e-4, 3e-4, 1e-3, 3e-3, 1e-2]
- 3 entropy coefficients: [0.001, 0.01, 0.05]
- Periodically copy weights from best performer

**Why This Helps:** Automatically finds best hyperparameters for this specific game.

---

#### 9. **Add Opponent Modeling**

Extend observation to include:
- Opponent action history (last 5 actions)
- Opponent resource usage patterns
- Estimated opponent hand strength

**Why This Helps:** Helps agent adapt to opponent strategies (important for tournament play).

---

#### 10. **Implement Recurrent Policy (LSTM/GRU)**

**Current:** Feedforward policy (stateless)

**Recommended:** Add LSTM layer to policy network

```python
# In train_sb3.py, use RecurrentPPO instead of PPO
from sb3_contrib import RecurrentPPO

model = RecurrentPPO(
    "MultiInputLstmPolicy",  # Use LSTM policy
    env,
    # ... other params
)
```

**Why This Helps:** Maintains memory of opponent plays and deck composition over time.

---

## Implementation Roadmap

### Week 1: Quick Wins (High Priority)
- [ ] Implement improved reward shaping (#1)
- [ ] Add entropy coefficient (#2)
- [ ] Run 1M timestep training (#3)
- [ ] Evaluate against heuristic bot

### Week 2: Architecture (Medium Priority)
- [ ] Implement 3-phase curriculum learning (#5)
- [ ] Generate heuristic demonstration data
- [ ] Train behavioral cloning warm-start model (#7)
- [ ] Retrain with BC initialization

### Week 3: Advanced (Low Priority)
- [ ] Experiment with recurrent policy (#10)
- [ ] Try population-based training (#8)
- [ ] Add opponent modeling features (#9)

---

## Quick Start: Minimal Training Command

To test improvements immediately, run:

```bash
# Improved training with quick wins
python -m scripts.train_sb3 \
    --total-timesteps 1000000 \
    --learning-rate 3e-4 \
    --n-steps 4096 \
    --batch-size 256 \
    --ent-coef 0.01 \
    --checkpoint-dir checkpoints_improved
```

Then update `env.py` reward parameters in `train_sb3.py:120-123`:
```python
reward_step=-0.005,
reward_on_hit=0.5,
reward_good_block=0.3,
reward_overpitch=-0.2,
```

---

## Expected Results

With these improvements:

- **After 100k steps**: Agent should learn basic game mechanics (was: random play)
- **After 500k steps**: Agent should match ~40-45% win rate vs heuristic (was: <20%)
- **After 1M steps**: Agent should match ~45-50% win rate vs heuristic
- **After 5M steps**: Agent should exceed 55%+ win rate vs heuristic (stretch goal from ML_BOT_PLAN.md)

---

## Debugging Training

### Monitor These Metrics

**During Training:**
- Episode return (should increase from ~-20 to positive)
- Episode length (should stabilize around 30-50 turns)
- Entropy (should start high and decay gradually)
- Explained variance (should be >0.5, indicates value function learning)
- Win rate vs heuristic (track every 50k steps)

**Signs of Problems:**
- ❌ Episode return stays negative: Rewards too sparse or agent not learning
- ❌ Entropy drops to near-zero early: Premature convergence, increase ent_coef
- ❌ Episode length >100 turns: Games stuck in loops, add stronger step penalty
- ❌ Explained variance <0.3: Value function not learning, check reward scale

---

## Additional Resources

**Relevant Files:**
- Training: `scripts/train_sb3.py`
- Environment: `fabgame/rl/env.py`
- Rewards: `env.py:234-264`
- Action space: `fabgame/rl/action_mask.py`
- Heuristic baseline: `fabgame/agents/heuristic.py`
- Evaluation: `scripts/eval_agents.py`

**Key Papers:**
- PPO: "Proximal Policy Optimization" (Schulman et al., 2017)
- Action Masking: "Action Branching Architectures" (Tavakoli et al., 2018)
- Reward Shaping: "Policy Invariance Under Reward Transformations" (Ng et al., 1999)

---

## Summary

Your ML agent is struggling because:
1. **Sparse rewards** - No feedback during 50+ turn games
2. **Huge action space** - 30k+ actions to explore
3. **Strong baseline** - Heuristic uses optimal greedy strategy
4. **Insufficient training** - 100k steps too few
5. **No exploration** - Zero entropy coefficient

**Quick wins** (implement this week):
- Better reward shaping (+life delta, +efficiency, +blocking)
- Entropy coefficient (0.01)
- 10x more training (1M steps)
- Larger batches (256)

**Expected improvement**: 20% → 45-50% win rate vs heuristic

Good luck! 🎮
