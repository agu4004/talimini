from __future__ import annotations

# Core gameplay configuration values.
STARTING_LIFE = 20
INTELLECT = 4
DEFEND_MAX = 2               # Maximum defend cards allowed per response.
MAX_PITCH_ENUM = None        # Limit combinations enumerated for pitching; None means unlimited.
DEFAULT_DECK_DIR = "data/decks"
USE_COLOR = True             # Toggle ANSI colours in console output.

# Random deck generation constants (for testing)
RANDOM_DECK_ATTACK_CARDS = 8
RANDOM_DECK_DEFENSE_CARDS = 8
RANDOM_CARD_COSTS = [1, 2, 3]
RANDOM_CARD_ATTACKS = [3, 4, 5, 6]
RANDOM_CARD_DEFENSES = [2, 3]
RANDOM_CARD_PITCH_VALUES = [1, 2, 3]

# Bot scoring constants
BOT_WEAPON_TYPE_BIAS = 2
BOT_HIGH_PRIORITY_SCORE = 999

# Phase transition constants
PHASE_PASS_THRESHOLD = 2     # Number of consecutive passes to end a phase

