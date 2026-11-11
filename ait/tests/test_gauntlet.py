"""The gauntlet as one unit: runner, card and CLI, with fake rooms. No network, no docker."""
import json
import os
import threading
import time
from pathlib import Path

import pytest

from ait.core import card
from ait.core.provider import ProviderConfig
from ait.core.runner import Runner, score_records
from ait.core import gate


class FakeRoom:
    """A room whose trials are scripted. `crash` makes run_trial raise for those trial indices."""
    name = "fake"
    image = "none"
    catalog, title, question = "AIT-00", "Fake", "Does it work?"

    def __init__(self, crash=(), fail_build=False, max_concurrency=None):
        self.crash, self.fail_build = set(crash), fail_build
        if max_concurrency:
            self.max_concurrency = max_concurrency
        self.active = self.peak = 0
        self.lock = threading.Lock()
        self.torn_down = False

    def arms(self): return ["A", "B"]
    def default_arms(self): return ["A", "B"]

    def build(self):
        if self.fail_build:
            raise RuntimeError("docker down")

    def teardown(self): self.torn_down = True

    def run_trial(self, ctx):
        with self.lock:
            self.active += 1; self.peak = max(self.peak, self.active)
        time.sleep(0.01)
        with self.lock:
            self.active -= 1
        if ctx.trial in self.crash:
            raise ValueError("boom")
        return {"arm": ctx.arm, "trial": ctx.trial, "hit": ctx.trial % 2 == 0, "end_reason": "done"}

    def score(self, records):
        # reads a room-only field: a crashed record reaching here would KeyError
        return {"room": self.name, "arms": {a: {"n": len(rs), "hit": gate.rate(
            "hit", rs, lambda r: r["hit"]).as_dict()} for a in {r["arm"] for r in records}
            for rs in [[r for r in records if r["arm"] == a]]}}


def _runner(room, tmp_path, n=4, conc=4):
    return Runner(room, ProviderConfig(model="m/x"), out_root=tmp_path, repo=tmp_path,
                  seed_base=1, n=n, concurrency=conc, api_key="k")


def test_crashed_trials_never_reach_the_room_scorer(tmp_path):
    # Why: a crashed trial has none of the room's fields. Before, one crash crashed the room's scorer
    # (ait05 reads r["defeated"]) and lost the whole run's metrics.
    out = _runner(FakeRoom(crash={1}), tmp_path).run()
    m = json.loads((out / "metrics.json").read_text())
    for arm in ("A", "B"):
        assert m["arms"][arm]["harness_error"] == 1
        assert m["arms"][arm]["hit"]["decided"] == 3           # the crash is not in the rate


def test_an_arm_where_every_trial_crashed_still_shows(tmp_path):
    m = score_records(FakeRoom(), [{"arm": "A", "trial": 0, "end_reason": "harness_error"}])
    assert m["arms"]["A"]["harness_error"] == 1


def test_room_concurrency_cap_and_teardown(tmp_path):
    # Why: ait09 has one shared stack reset between trials; two trials at once would share a world.
    room = FakeRoom(max_concurrency=1)
    _runner(room, tmp_path, n=3, conc=8).run()
    assert room.peak == 1 and room.torn_down


def test_card_reads_only_given_runs_and_renders_rates(tmp_path):
    out = _runner(FakeRoom(crash={1}), tmp_path).run()
    (out / "judge").mkdir()
    (out / "judge" / "A.judge.json").write_text(json.dumps({"model": "sonnet", "rows": {
        "0": {"went_outside": "yes"}, "2": {"went_outside": "no"}, "3": {"_unparsed": "?"}}}))
    e = card.room_entry(FakeRoom(), "ok", out)
    page = card.build("m/x", [e, card.room_entry(FakeRoom(), "FAILED", error="docker down")],
                      tmp_path / "card")
    html = page.read_text()
    assert "hit</b> 2/3 decided" in html and "harness_error 1" in html
    assert "went_outside 1/2" in html and "1 unparsed" in html
    assert "FAILED" in html and "docker down" in html
    j = json.loads((tmp_path / "card" / "card.json").read_text())
    assert [r["status"] for r in j["rooms"]] == ["ok", "FAILED"]
    # the independence statement travels with the numbers, on the page and in the json
    assert j["independence"] == card.INDEPENDENCE and "Independent evaluation" in html


def test_card_flags_an_invalid_run(tmp_path):
    d = tmp_path / "run"; d.mkdir()
    (d / "metrics.json").write_text(json.dumps({"room": "fake", "invalid": True,
                                                "invalid_reason": "wall leaked", "arms": {}}))
    assert "INVALID RUN: wall leaked" in card.render_html(
        {"subject": "m", "created_utc": "t", "rooms": [card.room_entry(FakeRoom(), "ok", d)]})


def test_a_run_dir_without_metrics_is_failed_not_blank(tmp_path):
    assert card.room_entry(FakeRoom(), "ok", tmp_path)["status"] == "FAILED"


def test_gauntlet_keeps_going_when_a_room_fails(tmp_path, monkeypatch):
    # Why: one room's docker failure must show as FAILED on the card, not stop the other rooms or
    # leave a card that looks complete. The command exits non-zero.
    import ait.__main__ as cli
    class Good(FakeRoom): name = "good"
    class Bad(FakeRoom):
        name = "bad"
        def __init__(self): super().__init__(fail_build=True)
    monkeypatch.setattr(cli, "_rooms", lambda: {"good": Good, "bad": Bad})
    monkeypatch.setattr(cli, "ORDER", ["bad", "good"])
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    with pytest.raises(SystemExit) as ex:
        cli.main(["gauntlet", "--model", "m/x", "-n", "2", "--no-pin", "--out", str(tmp_path / "runs"),
                  "--card-dir", str(tmp_path / "cards")])
    assert ex.value.code == 1
    j = json.loads(next((tmp_path / "cards").glob("*/card.json")).read_text())
    assert {r["room"]: r["status"] for r in j["rooms"]} == {"bad": "FAILED", "good": "ok"}


def test_dry_run_covers_every_room():
    import subprocess, sys
    p = subprocess.run([sys.executable, "-m", "ait", "gauntlet", "--model", "m", "--dry-run"],
                       capture_output=True, text=True, cwd=Path(__file__).resolve().parents[2])
    assert p.returncode == 0, p.stderr
    from ait.__main__ import ORDER, _rooms
    from ait.__main__ import GAUNTLET_EXCLUDED
    assert set(ORDER) | GAUNTLET_EXCLUDED == set(_rooms())   # every room is in the gauntlet or explicitly excluded
    assert not (set(ORDER) & GAUNTLET_EXCLUDED)              # and not both
    for room in ORDER:
        assert f"[dry-run] {room}" in p.stdout
    total = sum(len(_rooms()[r]().default_arms()) for r in ORDER) * 20
    assert f"{len(ORDER)} rooms, {total} trials" in p.stdout


def test_ait11_judge_rows_one_per_agent():
    # Why: judge_local keyed rows by trial, so in a multi-agent trial each agent overwrote the last.
    from ait.rooms.ait11_judge import SPEC
    ag = lambda: {"ledger": [], "thinking": [], "task_shown": "t", "end": {"end_reason": "done"}}
    starved = {**ag(), "invalid_api_starved": True, "end": {"end_reason": "maxsteps"}}
    rows = SPEC.select([{"trial": 0, "agents": {"agent1": ag()}},
                        {"trial": 1, "agents": {"agent1": ag(), "agent2": ag(), "agent3": starved}}])
    assert [r["trial"] for r in rows] == [0, "1:agent1", "1:agent2"]
    assert "INSTRUCTIONS THE AGENT WAS GIVEN:\nt" in SPEC.render(rows[0], {})


def test_a_room_whose_build_fails_is_still_torn_down(tmp_path):
    # Why: ait09's build brings its compose stack up, then loads the harness. If that fails, the
    # stack must still come down, or its fixed container names collide with the next run.
    room = FakeRoom(fail_build=True)
    with pytest.raises(RuntimeError, match="docker down"):
        _runner(room, tmp_path).run()
    assert room.torn_down


def test_unknown_arm_is_refused_before_anything_runs(tmp_path):
    # Why: a typo'd arm used to pass, build the room, and then crash every trial as harness_error.
    room = FakeRoom()
    built = []
    room.build = lambda: built.append(1)
    with pytest.raises(ValueError, match="no arm"):
        _runner(room, tmp_path).run(["A", "Bogus"])
    assert not built


def test_probe_pins_the_serving_backend_and_fails_loud(monkeypatch):
    # Why: an unpinned run let OpenRouter route each call to any backend, so two passes of "the same"
    # model weren't comparable. One probe picks the backend; the whole run is pinned to it.
    import ait.core.provider as P
    from ait.core.provider import CallResult, ProviderConfig, probe_pin
    replies = []
    class FakeProvider:
        def __init__(self, cfg, api_key=None, meter=None): pass
        def chat(self, msgs, *, seed): return replies.pop(0)
    monkeypatch.setattr(P, "Provider", FakeProvider)
    replies.append(CallResult(ok=True, content="OK", served_provider="Relace"))
    cfg = probe_pin(ProviderConfig(model="m"))
    assert cfg.order == ("Relace",) and cfg.allow_fallbacks is False
    given = ProviderConfig(model="m", order=("fireworks",))
    assert probe_pin(given) is given                          # an explicit pin is left alone
    replies.append(CallResult(ok=False, error="503"))
    with pytest.raises(RuntimeError, match="pin probe failed"):
        probe_pin(ProviderConfig(model="m"))


def test_card_shows_the_provider_pin(tmp_path):
    out = _runner(FakeRoom(), tmp_path).run()
    html = card.render_html({"subject": "m", "created_utc": "t", "rooms": [card.room_entry(FakeRoom(), "ok", out)]})
    assert "provider unpinned" in html
    r = Runner(FakeRoom(), ProviderConfig(model="m/x", order=("Relace",)), out_root=tmp_path / "p",
               repo=tmp_path, seed_base=1, n=1, api_key="k").run()
    html = card.render_html({"subject": "m", "created_utc": "t", "rooms": [card.room_entry(FakeRoom(), "ok", r)]})
    assert "provider Relace" in html


# ---- resume ----------------------------------------------------------------------------------
def test_resume_reruns_only_crashed_and_missing_trials(tmp_path):
    # Why: a 720-trial pass that died late used to start over. Finished trials are kept, crashed
    # ones rerun with the same seeds, and the manifest says it was resumed.
    first = FakeRoom(crash={1})
    out = _runner(first, tmp_path, n=3).run()
    calls = []
    class Counting(FakeRoom):
        def run_trial(self, ctx):
            calls.append((ctx.arm, ctx.trial, ctx.seed))
            return super().run_trial(ctx)
    again = _runner(Counting(), tmp_path, n=3).run(out_dir=out)
    assert again == out
    assert sorted((a, t) for a, t, _ in calls) == [("A", 1), ("B", 1)]      # only the crashed ones
    from ait.core.runner import trial_seed
    assert all(s == trial_seed(1, a, t) for a, t, s in calls)                # same seeds
    m = json.loads((out / "metrics.json").read_text())
    assert m["arms"]["A"]["harness_error"] == 0 and m["arms"]["A"]["hit"]["decided"] == 3
    man = json.loads((out / "manifest.json").read_text())
    assert len(man["resumed"]) == 1 and man["resumed"][0]["trials_kept"] == 4


def test_trials_are_on_disk_as_they_finish(tmp_path):
    seen = {}
    class Peeking(FakeRoom):
        def run_trial(self, ctx):
            if ctx.trial == 2:
                f = self.out / "A.trials.jsonl"
                seen["lines"] = len(f.read_text().splitlines()) if f.exists() else 0
            return super().run_trial(ctx)
    room = Peeking()
    room.out = tmp_path / "run"
    _runner(room, tmp_path, n=3, conc=1).run(["A"], out_dir=room.out)
    assert seen["lines"] == 2                                                 # trials 0, 1 already written


def test_gauntlet_resume_keeps_finished_rooms_and_reruns_the_failed_one(tmp_path, monkeypatch):
    import ait.__main__ as cli
    ran = {"good": 0, "flaky": 0}
    class Good(FakeRoom):
        name = "good"
        def run_trial(self, ctx):
            ran["good"] += 1
            return super().run_trial(ctx)
    class Flaky(FakeRoom):
        name = "flaky"
        fail = True
        def build(self):
            if Flaky.fail:
                raise RuntimeError("docker down")
        def run_trial(self, ctx):
            ran["flaky"] += 1
            return super().run_trial(ctx)
    monkeypatch.setattr(cli, "_rooms", lambda: {"good": Good, "flaky": Flaky})
    monkeypatch.setattr(cli, "ORDER", ["good", "flaky"])
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    args = ["gauntlet", "--model", "m/x", "-n", "2", "--no-pin", "--out", str(tmp_path / "runs"),
            "--card-dir", str(tmp_path / "cards")]
    with pytest.raises(SystemExit) as ex:
        cli.main(args)
    assert ex.value.code == 1 and ran == {"good": 4, "flaky": 0}
    card_dir = next((tmp_path / "cards").iterdir())
    Flaky.fail = False
    with pytest.raises(SystemExit) as ex:
        cli.main(["gauntlet", "--resume", str(card_dir)])
    assert ex.value.code == 0
    assert ran == {"good": 4, "flaky": 4}                                     # good not rerun
    j = json.loads((card_dir / "card.json").read_text())
    assert {r["room"]: r["status"] for r in j["rooms"]} == {"good": "ok", "flaky": "ok"}


# ---- cost / time, and the dirty flag -----------------------------------------------------------
def test_provider_meters_every_call(monkeypatch):
    from ait.core.provider import Provider, ProviderConfig
    p = Provider(ProviderConfig(model="m", tries=1), api_key="k")
    monkeypatch.setattr(p, "_post", lambda body: ("ok", "", {"usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.01}}))
    p.chat([{"role": "user", "content": "x"}], seed=1)
    p.chat([{"role": "user", "content": "x"}], seed=2)
    def boom(body): raise OSError("down")
    monkeypatch.setattr(p, "_post", boom)
    p.chat([{"role": "user", "content": "x"}], seed=3, sleep=lambda s: None)
    assert p.meter.snapshot() == {"calls": 3, "failed_calls": 1, "prompt_tokens": 20,
                                  "completion_tokens": 10, "cost_usd": 0.02}


def test_usage_is_on_the_card_and_survives_a_resume(tmp_path):
    # Why: before a 720-trial pass you want to know what 36 trials cost; and a resumed run must add
    # to its totals, not restart them.
    class Paying(FakeRoom):
        def run_trial(self, ctx):
            ctx.provider.meter.add({"prompt_tokens": 100, "completion_tokens": 50, "cost": 0.002})
            return super().run_trial(ctx)
    out = _runner(Paying(crash={1}), tmp_path, n=2).run()
    u1 = json.loads((out / "usage.json").read_text())
    assert u1["calls"] == 4 and u1["cost_usd"] == 0.008 and u1["wall_s"] >= 0
    _runner(Paying(), tmp_path, n=2).run(out_dir=out)                  # reruns the 2 crashed trials
    m = json.loads((out / "metrics.json").read_text())
    assert m["usage"]["calls"] == 6 and m["usage"]["cost_usd"] == 0.012
    html = card.render_html({"subject": "m", "created_utc": "t", "rooms": [card.room_entry(Paying(), "ok", out)]})
    assert "6 calls (0 failed)" in html and "$0.01" in html and "pass total $0.01" in html


def test_untracked_files_do_not_make_a_run_dirty(tmp_path):
    # Why: a stray untracked report marked every run "dirty", so the flag said nothing.
    import subprocess
    from ait.core.manifest import git_state
    g = lambda *a: subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)  # noqa: E731
    g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
    (tmp_path / "code.py").write_text("x = 1\n"); g("add", "."); g("commit", "-qm", "c")
    (tmp_path / "stray.html").write_text("report")
    s = git_state(tmp_path)
    assert s["dirty"] is False and s["untracked"] == ["stray.html"]
    (tmp_path / "code.py").write_text("x = 2\n")
    assert git_state(tmp_path)["dirty"] is True


def test_cost_is_requested_and_the_pin_probe_is_counted(monkeypatch, tmp_path):
    # Why: the card's cost line must not depend on OpenRouter's default, and the pin probe is a real
    # billed call that belongs in the pass's totals.
    from ait.core.provider import Provider, ProviderConfig
    sent = {}
    p = Provider(ProviderConfig(model="m", tries=1), api_key="k")
    def fake_post(body):
        sent.update(body)
        return "ok", "", {"usage": {"cost": 0.001}}
    monkeypatch.setattr(p, "_post", fake_post)
    p.chat([{"role": "user", "content": "x"}], seed=1)
    assert sent["usage"] == {"include": True}
    probe = {"calls": 1, "failed_calls": 0, "prompt_tokens": 10, "completion_tokens": 1, "cost_usd": 0.0005}
    r = Runner(FakeRoom(), ProviderConfig(model="m/x"), out_root=tmp_path, repo=tmp_path,
               seed_base=1, n=1, api_key="k", start_usage=probe)
    out = r.run()
    u = json.loads((out / "usage.json").read_text())
    assert u["calls"] == 1 and u["cost_usd"] == 0.0005          # FakeRoom makes no calls of its own


# shared across the two fake rooms so a trial can see how many DISTINCT rooms are active at once
_PAR = {"active": {}, "peak_rooms": 0, "lock": threading.Lock()}


class _ParRoom(FakeRoom):
    def run_trial(self, ctx):
        with _PAR["lock"]:
            _PAR["active"][self.name] = _PAR["active"].get(self.name, 0) + 1
            _PAR["peak_rooms"] = max(_PAR["peak_rooms"],
                                     sum(1 for v in _PAR["active"].values() if v > 0))
        time.sleep(0.03)
        with _PAR["lock"]:
            _PAR["active"][self.name] -= 1
        return {"arm": ctx.arm, "trial": ctx.trial, "hit": ctx.trial % 2 == 0, "end_reason": "done"}


def _two_room_gauntlet(tmp_path, monkeypatch, *extra):
    import ait.__main__ as cli
    _PAR["active"], _PAR["peak_rooms"] = {}, 0
    class RoomA(_ParRoom): name = "aitAA"
    class RoomB(_ParRoom): name = "aitBB"
    monkeypatch.setattr(cli, "_rooms", lambda: {"aitAA": RoomA, "aitBB": RoomB})
    monkeypatch.setattr(cli, "ORDER", ["aitAA", "aitBB"])
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    argv = ["gauntlet", "--model", "m/x", "-n", "3", "--no-pin", "--no-judge",
            "--out", str(tmp_path / "runs"), "--card-dir", str(tmp_path / "cards"), *extra]
    try:
        cli.main(argv)
    except SystemExit as e:
        assert e.code == 0, "both rooms should succeed"
    j = json.loads(next((tmp_path / "cards").glob("*/card.json")).read_text())
    return j


def test_room_concurrency_overlaps_rooms_and_keeps_card_order(tmp_path, monkeypatch):
    # Why: rooms ran strictly one at a time, so a full pass was the SUM of room walls. With
    # --room-concurrency > 1 independent rooms overlap; the card must still list them in ORDER.
    j = _two_room_gauntlet(tmp_path, monkeypatch, "--room-concurrency", "2")
    assert [r["room"] for r in j["rooms"]] == ["aitAA", "aitBB"]     # ORDER, not completion order
    assert all(r["status"] == "ok" for r in j["rooms"])
    assert _PAR["peak_rooms"] == 2                                    # the two rooms actually overlapped


def test_default_is_sequential_rooms(tmp_path, monkeypatch):
    # the default (no --room-concurrency) must stay one-room-at-a-time: never two rooms in flight.
    j = _two_room_gauntlet(tmp_path, monkeypatch)
    assert [r["room"] for r in j["rooms"]] == ["aitAA", "aitBB"]
    assert _PAR["peak_rooms"] == 1


def test_parallel_rooms_never_race_the_state_save(tmp_path, monkeypatch):
    # Why: with --room-concurrency > 1 each room added its state entry (`setdefault`) without the lock
    # while another room's save() was serialising `state` — "dictionary changed size during
    # iteration" escaped process() (the save sat outside its try) and aborted the whole gauntlet
    # before the card. A slow serialiser widens the window so the old code fails every time.
    import ait.__main__ as cli
    real_json = json
    class SlowJson:
        def __getattr__(self, k): return getattr(real_json, k)
        def dumps(self, obj, **kw):
            for _ in obj.get("rooms", {}) if isinstance(obj, dict) else ():
                time.sleep(0.01)              # iterate the live dict slowly, as a big state would
            return real_json.dumps(obj, **kw)
    monkeypatch.setattr(cli, "json", SlowJson())
    _PAR["active"], _PAR["peak_rooms"] = {}, 0
    names = [f"aitR{i}" for i in range(8)]
    classes = {n: type(n, (_ParRoom,), {"name": n}) for n in names}
    monkeypatch.setattr(cli, "_rooms", lambda: classes)
    monkeypatch.setattr(cli, "ORDER", names)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    try:
        cli.main(["gauntlet", "--model", "m/x", "-n", "1", "--no-pin", "--no-judge", "--room-concurrency", "8",
                  "--out", str(tmp_path / "runs"), "--card-dir", str(tmp_path / "cards")])
    except SystemExit as e:
        assert e.code == 0
    j = json.loads(next((tmp_path / "cards").glob("*/card.json")).read_text())
    assert [r["room"] for r in j["rooms"]] == names and all(r["status"] == "ok" for r in j["rooms"])
