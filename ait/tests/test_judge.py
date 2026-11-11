"""Blind judge: parse/enum validation and the ait12 answer-blindness fix — no claude calls."""
from ait.core.judge import BlindJudge, JudgeSpec
from ait.rooms import ait12_judge as J


def _spec():
    return JudgeSpec(name="t", rubric="R", keys=["a", "b"],
                     enums={"a": {"yes", "no"}}, render=lambda row, s: "x")


def test_parse_valid():
    bj = BlindJudge(_spec())
    r = bj.parse('junk {"a":"YES","b":"free text"} tail')
    assert r == {"a": "yes", "b": "free text"}


def test_parse_off_rubric_enum_is_unparsed():
    bj = BlindJudge(_spec())
    r = bj.parse('{"a":"maybe","b":"x"}')
    assert "_unparsed" in r and "off-rubric" in r["_unparsed"]


def test_parse_missing_key_is_unparsed():
    bj = BlindJudge(_spec())
    r = bj.parse('{"a":"yes"}')
    assert "_unparsed" in r


def test_no_json_is_unparsed():
    assert "_unparsed" in BlindJudge(_spec()).parse("no braces here")


# ---- ait12 render: the answer-blindness fix --------------------------------

def _row(**kw):
    base = {"task": "get metric M", "thinking": [{"turn": 0, "reasoning": "think"}],
            "ledger": [{"turn": 0, "cmd": "ls", "out": "files"}]}
    base.update(kw)
    return base


def test_render_shows_final_answer():
    v = J.render(_row(end_reason="answer", final_answer="4.73"), {})
    assert "ANSWER: 4.73" in v
    assert "get metric M" in v          # task shown
    assert "P2" not in v and "P3" not in v   # arm never leaked


def test_render_shows_giveup():
    v = J.render(_row(end_reason="giveup", giveup_reason="GIVEUP: no route"), {})
    assert "no route" in v


def test_render_marks_no_answer_when_maxsteps():
    v = J.render(_row(end_reason="maxsteps"), {})
    assert "no final answer" in v and "maxsteps" in v


def test_render_does_not_leak_correctness():
    # answer_correct is in the record but must not appear in the blind view
    v = J.render(_row(end_reason="answer", final_answer="9.99", answer_correct=False), {})
    assert "correct" not in v.lower()


def test_render_reports_cut_stats():
    stats = {}
    long = "z" * 50000
    J.render(_row(thinking=[{"turn": 0, "reasoning": long}]), stats)
    assert stats["_reasoning_chars_cut"] > 0
