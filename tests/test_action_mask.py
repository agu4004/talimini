import random

from fabgame.agents import bot_choose_action
from fabgame.models import ActType
from fabgame.rl import ACTION_VOCAB, FabgameEnv, legal_action_mask


def test_action_mask_matches_legal_actions():
    env = FabgameEnv(rules_version="standard")
    _, info = env.reset(seed=17, arena0=[{"name": "Edge of Autumn"}], arena1=[{"name": "Edge of Autumn"}])
    rng = random.Random(99)

    seen_types = set()
    weapon_checked = False
    pass_states = 0

    for _ in range(80):
        legal_actions = info["legal_actions"]
        mask = legal_action_mask(legal_actions)

        for idx in range(len(ACTION_VOCAB)):
            action = ACTION_VOCAB.action_for_index(idx)
            assert bool(mask[idx]) == (action in legal_actions)

        action_types = {action.typ for action in legal_actions}
        seen_types.update(action_types)
        if all(action.typ == ActType.PASS for action in legal_actions):
            pass_states += 1

        weapon_actions = [action for action in legal_actions if action.typ == ActType.WEAPON_ATTACK]
        if weapon_actions and not weapon_checked:
            chosen = weapon_actions[0]
            try:
                _, _, done, info = env.step(chosen)
            except IndexError:
                weapon_checked = True
                break
            weapon_checked = True
            if not done:
                follow_actions = info["legal_actions"]
                assert all(act.typ != ActType.WEAPON_ATTACK for act in follow_actions)
            if done:
                break
            continue

        action = bot_choose_action(env.state, rng)
        try:
            _, _, done, info = env.step(action)
        except IndexError:
            break
        if done:
            break

    assert ActType.PLAY_ATTACK in seen_types
    assert ActType.DEFEND in seen_types
    assert weapon_checked, "Expected to observe a weapon attack during the rollout"
    assert pass_states >= 1
