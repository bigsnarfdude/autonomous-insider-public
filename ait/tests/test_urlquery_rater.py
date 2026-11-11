"""evidence/urlquery/u5_rate_claude.py: the second rater must stay blind to the rules, and an
off-rubric reply must never be counted as a label."""
import importlib.util
from pathlib import Path

_P = Path(__file__).resolve().parents[2] / "evidence" / "urlquery" / "u5_rate_claude.py"
spec = importlib.util.spec_from_file_location("u5", _P)
u5 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u5)

ROW = {"report_id": "r1", "url": "httpbin.org/base64/PGh0bWw-", "title": "t", "hosts": ["httpbin.org"],
       "n_decoded": 1, "decoded": "<html>", "class": "agent_like", "why": "route marker: collector",
       "raw_markers": ["collector"], "decoded_markers": []}


def test_view_is_blind_to_the_rules():
    # if the rater saw the rule's class or markers, agreement would be an echo, not a second opinion
    v = u5.view(ROW)
    for leak in ("agent_like", "route marker", "collector", "class"):
        assert leak not in v


def test_parse_accepts_a_valid_label():
    out = u5.parse('{"label": "agent_tradecraft", "techniques": ["relay", "fetch_handback"], '
                   '"target": "aihw.gov.au", "confidence": "high", "reason": "fetches and hands back"}')
    assert out["label"] == "agent_tradecraft" and out["techniques"] == ["relay", "fetch_handback"]


def test_parse_rejects_off_rubric_values():
    for bad in ('{"label": "malicious", "techniques": [], "confidence": "high"}',
                '{"label": "background", "techniques": ["hacking"], "confidence": "high"}',
                '{"label": "background", "techniques": [], "confidence": "sure"}',
                'no json here'):
        assert "_unparsed" in u5.parse(bad)
