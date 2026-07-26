"""v0.3 settlement quiz: silent answer key, player-authority nulls, verbatim
unhandled text. Origin: settlement design 2026-07-26 (protocol S3c)."""
import json, glob
from charactercheck import engine


def _fixture():
    return sorted(glob.glob("tests/fixtures/*.json"))[0]


def test_quiz_has_answer_key_and_player_nulls():
    q = engine.quiz(_fixture())
    asks = {x["ask"]: x for x in q["questions"]}
    ac = next(x for x in q["questions"] if "AC" in x["ask"])
    assert isinstance(ac["expect"], int)
    hp_now = next(x for x in q["questions"] if "right now" in x["ask"])
    assert hp_now["expect"] is None and hp_now["authority"] == "player"
    assert "SILENT" in q["contract"]


def test_quiz_caveat_matches_unhandled_lane():
    f = _fixture()
    q = engine.quiz(f)
    d = engine.derive(f)
    if d["unhandled"]["items"]:
        assert q["caveat"] and d["unhandled"]["items"][0]["pattern"] in q["caveat"]
    else:
        assert q["caveat"] is None


def test_unhandled_items_carry_verbatim_text_field():
    d = engine.derive(_fixture())
    for item in d["unhandled"]["items"]:
        assert "text" in item  # present (may be None for characterValues patterns)
