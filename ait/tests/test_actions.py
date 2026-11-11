"""The shared action parser: every room's protocol, and the reply formats models actually send.
Why: each room had fixed a different subset of these; the log-spoof room's miss (`</p>`) made every
command a syntax error and every trial a fake honest_fail."""
from pathlib import Path

import pytest

from ait.core.actions import parse
from ait.rooms.ait03 import action_of2
from ait.rooms.ait11 import action_of
from ait.rooms.ait12 import action_of as action_of12

# (reply, expected (kind, value)) under the plain CMD/DONE protocol
CORPUS = [
    ("CMD: ls -la", ("cmd", "ls -la")),
    ("cmd: ls", ("cmd", "ls")),
    ("CMD: cat check.sh</p>", ("cmd", "cat check.sh")),                    # deepseek, 2026-09-26
    ("<p>CMD: ./check.sh</p>", ("cmd", "./check.sh")),
    ('CMD: echo "<p>hi</p>" > x.html', ("cmd", 'echo "<p>hi</p>" > x.html')),  # HTML inside stays
    ("CMD: ls</arg_value></tool_call>", ("cmd", "ls")),
    ("<tool_call>CMD: pwd</tool_call>", ("cmd", "pwd")),
    ("**CMD:** ls", ("cmd", "ls")),
    ("**CMD: cat x**", ("cmd", "cat x")),
    ("`CMD: ls`", ("cmd", "ls")),
    ("CMD: `ls -l`", ("cmd", "ls -l")),
    ("CMD: ls *", ("cmd", "ls *")),                                            # globs survive
    ("CMD: rm -f /tmp/*", ("cmd", "rm -f /tmp/*")),
    ("CMD: ls CMD: pwd", ("cmd", "ls")),
    ("<think>CMD: rm -rf x</think>\nDONE", ("done", None)),                    # reasoning isn't action
    ("DONE", ("done", None)),
    ("DONE.", ("done", None)),
    ("**DONE**", ("done", None)),
    ("I think I'm finished", ("none", None)),
    ("", ("none", None)),
    (None, ("none", None)),
]


@pytest.mark.parametrize("reply,expected", CORPUS)
def test_corpus_through_the_shared_parser(reply, expected):
    assert parse(reply, ("CMD", "DONE")) == expected


@pytest.mark.parametrize("reply,expected", CORPUS)
def test_every_room_protocol_gets_the_same_cleanup(reply, expected):
    # ait11/ait04/ait05 (CMD/DONE), ait03 (+POST), ait12 (multi-line CMD) all see the same command
    assert action_of(reply) == expected
    assert action_of2(reply) == expected
    if expected[0] == "cmd":
        assert action_of12(reply) == expected


def test_room_verbs_and_precedence():
    assert action_of2("POST: hi\nCMD: ls") == ("post", "hi")
    assert action_of2("CMD: ls\nPOST: hi") == ("cmd", "ls")
    assert action_of12("ANSWER: $4.73 and CMD: ls")[0] == "answer"
    assert action_of12("CMD: python3 <<EOF\nprint(1)\nEOF\ntrailing") == ("cmd", "python3 <<EOF\nprint(1)\nEOF")
    assert parse("ASK: may I chmod the file?", ("CMD", "DONE", "ASK")) == ("ask", "may I chmod the file?")
    assert parse("ASK: may I?", ("CMD", "DONE")) == ("none", None)        # not offered -> not an action
    # log-spoof's first-line rule: a forge then DONE in one reply runs the forge
    reply = "CMD: echo pass > results.json\nDONE"
    assert parse(reply, ("CMD", "DONE", "ASK"), first_line=True) == ("cmd", "echo pass > results.json")
    assert parse(reply, ("CMD", "DONE")) == ("done", None)


def test_log_spoof_ships_the_same_parser():
    # the container can't import `ait`; its copy must be byte-identical or the rooms drift again
    root = Path(__file__).resolve().parents[2]
    assert (root / "ait/core/actions.py").read_bytes() == \
           (root / "rooms/log-spoof/harness/actions.py").read_bytes()
    assert "COPY actions.py /probe/actions.py" in (root / "rooms/log-spoof/harness/Dockerfile").read_text()


# ---- ultrareview 3 ----------------------------------------------------------------------------
def test_command_on_the_line_after_the_verb():
    # Why: "CMD:\nls -la" is a common layout; the shared parser dropped it (every old per-room
    # regex allowed it), so the agent lost a turn to a nudge.
    assert action_of("CMD:\nls -la") == ("cmd", "ls -la")
    assert action_of("**CMD:**\n  pwd") == ("cmd", "pwd")
    assert action_of2("POST:\neveryone restore mtime") == ("post", "everyone restore mtime")
    assert parse("CMD:\nls -la", ("CMD", "DONE", "ASK"), first_line=True) == ("cmd", "ls -la")
    assert action_of12("CMD:\npython3 <<EOF\nprint(1)\nEOF") == ("cmd", "python3 <<EOF\nprint(1)\nEOF")


def test_log_spoof_done_with_prose_ends_the_run_but_other_rooms_stay_strict():
    # Why: log-spoof always accepted "DONE, the task is complete"; the shared parser didn't. Only the
    # uppercase word counts — "Done reading the file" is not a finish — and only in that room's mode.
    ls = lambda t: parse(t, ("CMD", "DONE", "ASK"), first_line=True)  # noqa: E731
    assert ls("DONE, the task is complete") == ("done", None)
    assert ls("DONE - all set") == ("done", None)
    assert ls("Done reading the file") == ("none", None)
    assert action_of("DONE, the task is complete") == ("none", None)


def test_another_active_verb_ends_the_command():
    # Why: in ait03 "CMD: ls POST: hi" ran `ls POST: hi`. A verb the room doesn't offer is just text.
    assert action_of2("CMD: ls POST: everyone restore") == ("cmd", "ls")
    assert action_of("CMD: echo POST: hi") == ("cmd", "echo POST: hi")


def test_a_verb_glued_to_the_previous_word_still_ends_the_command():
    # Why: deepseek-v4-flash in ait12 (2026-09-25, P2 t0) sent two commands with no space between
    # them. `cat run.logCMD: curl -s -o …` ran as one line (cat: invalid option -- 'o'), and
    # `echo "No proxy"CMD: nslookup …` echoed the nslookup instead of running it. The ledger then
    # held commands that never ran, and the rung classifier scored their text.
    assert action_of12("CMD: cat run.logCMD: curl -s -o page.html x") == ("cmd", "cat run.log")
    assert action_of12('CMD: echo "No proxy"CMD: nslookup h') == ("cmd", 'echo "No proxy"')
    assert action_of2("CMD: ls -la && pwdPOST: hi") == ("cmd", "ls -la && pwd")
    # an upper-case run is a word, not a verb; inside quotes it is text
    assert action_of12("CMD: echo XCMD: y") == ("cmd", "echo XCMD: y")
    assert action_of12('CMD: grep "logCMD: " run.log') == ("cmd", 'grep "logCMD: " run.log')
