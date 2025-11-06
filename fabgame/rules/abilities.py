from __future__ import annotations

import ast
from typing import Optional

from ..io.card_yaml import load_card_from_yaml, pitch_to_color
from ..models import Card, GameState

_ALLOWED_NODES = (
    ast.Expression,
    ast.BoolOp,
    ast.UnaryOp,
    ast.BinOp,
    ast.Compare,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.And,
    ast.Or,
    ast.NotEq,
    ast.Eq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.Not,
)


def safe_eval_cond(expr: str, ctx: dict) -> bool:
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError(f"Disallowed node in condition: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id not in ctx:
            raise NameError(f"Unknown name in condition: {node.id}")
    compiled = compile(tree, "<cond>", "eval")
    return bool(eval(compiled, {"__builtins__": {}}, ctx))


def apply_on_declare_attack_modifiers(
    gs: GameState,
    base_attack: int,
    *,
    source_card: Optional[Card],
    is_weapon: bool,
) -> int:
    attack_value = base_attack
    ctx = _make_condition_context(gs, is_weapon=is_weapon, source_card=source_card)

    attack_value = _apply_hero_modifiers(gs, attack_value, ctx=ctx)
    attack_value = _apply_card_modifiers(gs, attack_value, source_card=source_card, ctx=ctx)

    return max(0, attack_value)


def _apply_card_modifiers(
    gs: GameState,
    attack_value: int,
    *,
    source_card: Optional[Card],
    ctx: dict,
) -> int:
    if not source_card:
        return attack_value

    color = pitch_to_color(getattr(source_card, "pitch", 0))
    yaml_data = load_card_from_yaml(source_card.name, color)
    if not yaml_data:
        return attack_value

    rules = ((yaml_data.get("modifiers") or {}).get("on_declare") or [])
    if not rules:
        return attack_value

    return _apply_rules(attack_value, rules, ctx=ctx)


def _apply_hero_modifiers(gs: GameState, attack_value: int, *, ctx: dict) -> int:
    you = gs.players[gs.turn]
    rules = ((you.hero_modifiers or {}).get("on_declare") or [])
    total = _apply_rules(attack_value, rules, ctx=ctx)

    if total == attack_value and you.hero == "Ira, Crimson Haze":
        if you.attacks_this_turn >= 1:
            total += 1

    return total


def _apply_rules(attack_value: int, rules, *, ctx: dict) -> int:
    total = attack_value
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        cond = rule.get("when")
        add_attack = rule.get("add_attack", 0)
        try:
            add_attack_val = int(add_attack)
        except Exception:
            continue
        if not add_attack_val:
            continue
        ok = True
        if cond:
            ok = safe_eval_cond(str(cond), ctx)
        if ok:
            total += add_attack_val
    return total


def _make_condition_context(gs: GameState, *, is_weapon: bool, source_card: Optional[Card]) -> dict:
    you = gs.players[gs.turn]
    attack_number = you.attacks_this_turn + 1
    ctx = {
        "attacks_this_turn": you.attacks_this_turn,
        "attack_number": attack_number,
        "pitch_sum": gs.last_pitch_sum,
        "is_weapon": is_weapon,
        "is_card": not is_weapon,
        "is_first_attack": you.attacks_this_turn == 0,
        "is_second_attack": you.attacks_this_turn == 1,
        "is_third_attack_or_higher": you.attacks_this_turn >= 2,
        "hero": you.hero,
    }
    if source_card is not None:
        ctx["card_name"] = source_card.name
    return ctx


__all__ = ["apply_on_declare_attack_modifiers", "safe_eval_cond"]
