
from fabgame.rl import FabgameEnv


def test_env_reset_step_and_restore():
    env = FabgameEnv(rules_version="standard")
    obs, info = env.reset(seed=21)

    assert "life" in obs
    assert obs["life"].shape == (2,)
    assert info["rules_version"] == "standard"

    snapshot = env.get_env_state()
    legal_actions = info["legal_actions"]
    assert legal_actions, "Expected at least one legal action on reset"

    next_obs, reward, done, next_info = env.step(legal_actions[0])
    assert isinstance(next_obs, dict)
    assert isinstance(reward, float)
    assert isinstance(done, bool)
    assert "legal_action_mask" in next_info

    if not done:
        env.restore(snapshot)
        assert env.state.turn == snapshot.state.turn
        assert env.state.phase == snapshot.state.phase

