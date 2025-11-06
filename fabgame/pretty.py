from __future__ import annotations

from typing import List, Optional, Tuple

from . import config


def _c(text: str, code: str) -> str:
    if not config.USE_COLOR:
        return text
    return f"[{code}m{text}[0m"


def _b(text: str) -> str:
    return _c(text, '1')


def _red(text: str) -> str:
    return _c(text, '31')


def _green(text: str) -> str:
    return _c(text, '32')


def _yellow(text: str) -> str:
    return _c(text, '33')


def _blue(text: str) -> str:
    return _c(text, '34')


def _cyan(text: str) -> str:
    return _c(text, '36')


def _dim(text: str) -> str:
    return _c(text, '2')


def pretty_event(ev: dict, life_after: Optional[Tuple[int, int]] = None) -> str:
    if not ev or 'type' not in ev:
        return _dim(' (no event)')
    event_type = ev['type']
    lines: List[str] = []

    if event_type == 'sot_to_action':
        lines.append(_b('??  Start of Turn -> Action'))
    elif event_type == 'pass_action':
        lines.append(_yellow('??  PASS - no attack'))
    elif event_type == 'declare_attack':
        card = ev.get('card', '?')
        attack = ev.get('attack', '?')
        cost = ev.get('cost', 0)
        pitch = ev.get('pitch_sum', 0)
        source = ev.get('source')
        lines.append(_b('??  ATTACK'))
        lines.append(f"    Card    : {_cyan(card)}")
        lines.append(f"    Attack  : {_red(str(attack))}")
        lines.append(f"    Cost    : {cost}    Pitch used: {pitch}")
        if source:
            lines.append(_dim(f'   source: {source}'))
    elif event_type == 'block_play':
        player = ev.get('player', '?')
        blocked = ev.get('blocked', 0)
        cards = ev.get('cards') or []
        lines.append(_blue('??  BLOCK'))
        lines.append(f"   Player {player} blocked {_blue(str(blocked))}")
        if cards:
            lines.append(_dim(f"   Cards : {', '.join(cards)}"))
    elif event_type == 'block_pass':
        player = ev.get('player', '?')
        lines.append(_dim(f"   Player {player} chooses not to block."))
    elif event_type == 'layer_pass':
        player = ev.get('player', '?')
        lines.append(_dim(f"   Player {player} passes priority on the layer step."))
    elif event_type == 'layer_end':
        lines.append(_dim("   Layer step closed."))
    elif event_type == 'defense_resolve':
        blocked = ev.get('blocked', 0)
        damage = ev.get('damage', 0)
        after = ev.get('def_life_after', '?')
        lines.append(_b('???  DEFENSE'))
        lines.append(f"    Blocked : {_blue(str(blocked))}")
        if damage > 0:
            lines.append(f"    Damage  : {_red(str(damage))}  -> Defender life: {_red(str(after))}")
        else:
            lines.append(f"    Damage  : {_green('0')}     -> Defender life: {_green(str(after))}")
        if ev.get('arsenal_defense'):
            lines.append(f"    Arsenal : {_cyan(ev['arsenal_defense'])}")
        if ev.get('go_again'):
            lines.append(_yellow('   -> Go again! Action point restored.'))
    elif event_type == 'end_phase_prompt':
        lines.append(_b('??  End Phase'))
        lines.append('   Set a card to arsenal or pass.')
    elif event_type == 'set_arsenal':
        player = ev.get('player', '?')
        card = ev.get('card', '?')
        lines.append(_b('??  ARSENAL SET'))
        lines.append(f'   Player {player} set {card}')
    elif event_type == 'skip_arsenal':
        player = ev.get('player', '?')
        lines.append(_dim(f'   Player {player} skipped arsenal.'))
    elif event_type == 'defense_react_play':
        player = ev.get('player', '?')
        blocked = ev.get('blocked', 0)
        cards = ev.get('cards') or []
        lines.append(_blue('??  Defense Reaction'))
        lines.append(f"   Player {player} blocked {_blue(str(blocked))}")
        if cards:
            joined = ", ".join(str(c) for c in cards)
            lines.append(_dim(f"   Cards : {joined}"))
    elif event_type == 'attack_react':
        player = ev.get('player', '?')
        card = ev.get('card', '?')
        bonus = ev.get('bonus', 0)
        source = ev.get('source', 'hand')
        pitch = ev.get('pitch_sum', 0)
        lines.append(_red('??  Attack Reaction'))
        lines.append(f"   Player {player} used {_cyan(card)} from {source}")
        lines.append(f"   Bonus : {_red(str(bonus))}   Pitch used: {pitch}")
    elif event_type == 'reaction_pass':
        player = ev.get('player', '?')
        lines.append(_dim(f'   Player {player} passes reactions.'))
    elif event_type == 'illegal_action':
        reason = ev.get('reason', 'Illegal action')
        action = ev.get('action')
        header = '??  ILLEGAL ACTION'
        lines.append(_yellow(header))
        if action:
            lines.append(f'   Action: {action}')
        lines.append(f'   Reason: {reason}')
        phase = ev.get('phase')
        combat_step = ev.get('combat_step')
        if phase or combat_step:
            lines.append(f'   Phase: {phase or "?"}  CombatStep: {combat_step or "?"}')
        if 'awaiting_defense' in ev:
            lines.append(f'   Awaiting defense: {bool(ev.get("awaiting_defense"))}')
    else:
        lines.append(_dim(f" {event_type}: {ev}"))

    if life_after is not None:
        lines.append(_dim(f"   ? Life now - P0: {life_after[0]} | P1: {life_after[1]}"))
    return '\n'.join(lines)


__all__ = ['pretty_event', '_b', '_dim']
