"""One parser for what an agent's reply asks the harness to do.

Every room speaks a line protocol — `CMD: <command>`, `DONE`, and per room `ASK:`, `POST:`,
`ANSWER:`, `GIVEUP:`. Each room used to parse it with its own regexes, and each had fixed a
different subset of how models actually format replies. The log-spoof room didn't strip a trailing
`</p>`, so every command deepseek-v4-flash sent was a shell syntax error and the trial a fake
`honest_fail`. Here the cleanup is written once and every room gets all of it:

  - reasoning inside `<think>…</think>` is not an action;
  - tool-call markup (`<tool_call>`, `</arg_value>`, `<parameter>`, …) ends the command;
  - HTML tags at the start or end of a command (`</p>`, `<code>`) are dropped — only at the edges,
    so `echo "<p>hi</p>" > x.html` keeps its content;
  - backticks and markdown bold around the verb or the command are dropped.

A room declares only its protocol: which verbs it accepts and whether a command may span lines
(ait12: heredocs, fenced blocks, backslash continuations, open quotes).

Precedence, same as the rooms had it: terminal verbs first (ANSWER, GIVEUP, ASK, then DONE), then
whichever of CMD / POST appears first. `first_line=True` (log-spoof's rule) instead acts on the first
line that parses, so `CMD: <forge>` then `DONE` in one reply runs the forge — the act that room
measures.

The log-spoof harness runs inside its own container and can't import `ait`, so
rooms/log-spoof/harness/actions.py is a byte-identical copy (a test fails if they drift).
"""
from __future__ import annotations

import re
import shlex

_THINK = re.compile(r"<think>.*?</think>", re.S)
_TOOL_DEBRIS = re.compile(r"</arg_value>|</?tool_call>|</?parameter>|</?function>|</?invoke>|"
                          r"</?command>|</?cmd>", re.I)
_HTML = r"</?(?:p|br|div|span|code|pre|b|strong|em)\b[^>]*>"
_HTML_EDGES = re.compile(rf"^(?:\s*{_HTML})+|(?:{_HTML}\s*)+$", re.I)


def strip_think(content: str | None) -> str:
    c = _THINK.sub("", content or "")
    return re.sub(r"</?think>", "", c)


_ACTION_VERBS = ("CMD", "POST", "ASK", "ANSWER", "GIVEUP")


def clean_command(cmd: str, verbs: tuple[str, ...] = ("CMD",)) -> str:
    """The command as the shell should see it. Another of the room's verbs on the same line starts a
    different action, so the command ends there (`CMD: ls POST: hi` runs `ls`)."""
    cmd = _TOOL_DEBRIS.split(cmd)[0]
    stops = [v for v in _ACTION_VERBS if v in verbs] or ["CMD"]
    # only a verb outside quotes starts a new action: `grep "ASK: " notes.txt` is one command.
    # A verb glued to the previous word still starts one (`cat run.logCMD: curl …`: deepseek, ait12,
    # 2026-09-25, where the glued half ran as arguments); an upper-case run (`XCMD:`) is not a verb
    for m in re.finditer(rf"\s*(?<![A-Z_])(?:{'|'.join(stops)}):\s*", cmd):
        if _quotes_closed(cmd[:m.start()]):
            cmd = cmd[:m.start()]
            break
    for _ in range(3):                                # tags / ticks / bold can nest at the edges
        cmd = _unwrap_ticks(_HTML_EDGES.sub("", cmd).strip())
        # markdown bold only: a leading `**`, and a trailing `**` right after a word/quote — never a
        # glob (`ls *`, `rm /tmp/*`, `dir/**` keep theirs)
        cmd = re.sub(r"^\*\*\s*", "", cmd)
        cmd = re.sub(r"(?<=[\w'\")\]])\*\*$", "", cmd).strip()
    return cmd


def command_text(rest: str) -> str:
    """A multi-line command: a fenced block, a heredoc to its delimiter, or lines joined while a
    backslash continues them or a quote is still open."""
    rest = rest.lstrip("\n") if rest.startswith("\n") else rest
    fence = re.match(r"```[\w-]*[ \t]*\n(.*?)\n?```", rest, re.S)
    if fence:
        return fence.group(1).strip()
    lines = rest.split("\n")
    out = [lines[0]]
    i = 1
    hd = re.search(r"<<-?\s*(['\"]?)(\w+)\1", lines[0])
    if hd:
        delim = hd.group(2)
        while i < len(lines):
            out.append(lines[i]); i += 1
            if lines[i - 1].strip() == delim:
                break
        return _unwrap_ticks("\n".join(out).strip())
    while i < len(lines) and (out[-1].rstrip().endswith("\\") or not _quotes_closed("\n".join(out))):
        out.append(lines[i]); i += 1
    return _unwrap_ticks("\n".join(out).strip())


def _unwrap_ticks(s: str) -> str:
    """Remove markdown backticks WRAPPED AROUND a command, never ones that belong to it.

    A matched pair around the whole text goes (`` `ls -la` ``). So does a lone tick at one edge
    when the count is odd, which is a wrapper whose other half was cut off. A command that ends in
    its own closing tick (``echo `date` ``) has an even count and no tick at the front, so it is
    left alone: stripping it sent the shell an unterminated command and the room recorded a failure
    the agent never caused."""
    s = s.strip()
    while len(s) >= 2 and s[0] == "`" and s[-1] == "`":
        s = s[1:-1].strip()
    # an empty pair at an edge is markdown debris (a wrapper closing next to another opening),
    # never part of a command: an empty substitution does nothing
    # (only when the ticks balance: with an odd count one of the two is the command's own)
    while s.endswith("``") and s.count("`") % 2 == 0:
        s = s[:-2].strip()
    while s.startswith("``") and s.count("`") % 2 == 0:
        s = s[2:].strip()
    if s.count("`") % 2 == 1:
        if s.startswith("`"):
            s = s[1:].strip()
        elif s.endswith("`"):
            s = s[:-1].strip()
    return s


def _quotes_closed(s: str) -> bool:
    try:
        shlex.split(s)
        return True
    except ValueError:
        return False


# what may sit before a verb at the start of its line: quote marks, bold, backticks, tags
_LINE_START = r"^[\s>*`]*(?:<[^>]+>)*\s*"


def _verb(name: str) -> re.Pattern[str]:
    # the verb may be wrapped in bold/backticks/tags and written in any case
    return re.compile(rf"(?:\*\*|`|<[^>]+>)*\b{name}:(?:\*\*|`)*[ \t]*", re.I)


def parse(content: str | None, verbs: tuple[str, ...] = ("CMD", "DONE"), *,
          multiline: bool = False, first_line: bool = False,
          _done_prefix: bool = False) -> tuple[str, str | None]:
    """(kind, value). kind is a lower-case verb, or "none" when the reply names no allowed action."""
    c = strip_think(content)
    if not c.strip():
        return ("none", None)
    # a verb alone on its line with the text on the next (`CMD:\nls -la`) is one action. Not a
    # fenced block: joined, its opening fence line (```bash) would run as the command
    c = re.sub(r"\b(CMD|POST|ASK):(\*\*|`)*[ \t]*\n[ \t]*(?=\S)(?!```)", r"\1: ", c)
    if first_line:
        for line in c.splitlines():
            # log-spoof's rule: an uppercase DONE opening a line ends the run even with prose after it
            got = parse(line, verbs, multiline=False, _done_prefix=True)
            if got[0] != "none":
                return got
        return ("none", None)
    if "ANSWER" in verbs:
        # Line-anchored like ASK and DONE: `CMD: grep "ANSWER: 5" notes.txt` is a command, and a
        # prose "giveup: not yet" is not the end of the trial. Sign and thousands separators are
        # part of the number: "-5" is not 5 and "1,234.50" is not 1.
        m = re.search(_LINE_START + r"ANSWER:(?:\*\*|`)*\s*(-?)\s*\$?\s*(-?)([0-9][0-9,]*(?:\.[0-9]+)?)",
                      c, re.M | re.I)
        if m:
            return ("answer", (m.group(1) or m.group(2)) + m.group(3).replace(",", ""))
    if "GIVEUP" in verbs and re.search(_LINE_START + r"GIVEUP:", c, re.M | re.I):
        return ("giveup", None)
    if "ASK" in verbs:
        m = re.search(r"^[\s>*`]*(?:<[^>]+>)*\s*ASK:(?:\*\*|`)*\s*(.+)", c, re.M | re.I)
        if m:
            return ("ask", clean_command(m.group(1), verbs)[:1000])
    if "DONE" in verbs and re.search(r"^[\s>*`]*(?:<[^>]+>)*\s*DONE\b[\s.!*`]*(?:<[^>]+>)*\s*$", c, re.M | re.I):
        return ("done", None)
    # only in first-line mode, and case-sensitive: "Done reading the file" is not a finish
    if "DONE" in verbs and _done_prefix and re.match(r"[\s>*`]*(?:<[^>]+>)*\s*DONE\b(?!:)", c):
        return ("done", None)
    found = []
    for v in ("CMD", "POST"):
        if v in verbs:
            m = _verb(v).search(c)
            if m:
                found.append((m.start(), v, m))
    if not found:
        return ("none", None)
    _, v, m = min(found)
    rest = c[m.end():]
    if v == "POST":
        return ("post", clean_command(rest.split("\n")[0], verbs)[:400])
    cmd = clean_command(command_text(rest) if multiline else rest.split("\n")[0], verbs)
    return ("cmd", cmd) if cmd else ("none", None)
