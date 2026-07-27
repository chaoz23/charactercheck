"""v0.4 seat pack. Origins: Devil's Sight narrated-blind failure and the
agent PC asking mid-scene for her own modifier (2026-07-27)."""
import json, os, glob
import pytest
from charactercheck import engine


def _fixture():
    return sorted(glob.glob("tests/fixtures/*.json"))[0]


def test_vision_finds_named_invocation_and_modifier():
    payload = {"modifiers": {"race": [{"subType": "darkvision", "value": 60}]},
               "classes": [{"classFeatures": [
                   {"name": "Eldritch Invocations"},
                   {"definition": {"name": "Devil's Sight",
                                   "snippet": "see normally in darkness ... 120 feet"}}]}]}
    v = engine.vision(payload)
    feats = {x["feature"]: x for x in v}
    assert feats["Darkvision"]["range_ft"] == 60
    assert feats["Devil's Sight"]["range_ft"] == 120


def test_seatpack_shape_and_persona_fence():
    p = engine.seatpack(_fixture())
    for k in ("abilities", "saves", "skills", "passives", "vision", "persona"):
        assert k in p
    assert p["persona"]["not_derivable"]          # absence is stated, never invented
    assert isinstance(p["passives"].get("passive_perception"), int)


def test_for_dm_redacts_player_authority():
    p = engine.seatpack(_fixture(), for_dm=True)
    hp = (p.get("combat") or {}).get("hp") or {}
    if "current" in hp:
        assert hp["current"] == "player-authority"


WILLIAM = os.path.expanduser("~/Projects/agent-table/fixtures/william.json")


@pytest.mark.skipif(not os.path.exists(WILLIAM), reason="private fixture, local only")
def test_regression_devils_sight_surfaces():
    d = engine.fetch(WILLIAM)
    feats = {x["feature"] for x in engine.vision(d)}
    assert "Devil's Sight" in feats
