"""Sandbox exec guarding: a wedged `docker exec` must never hang the gauntlet.

Field note: a full n=1 gauntlet pass hung 30+ min on ait11 — a worker stuck in `_buffered_readline`
(a docker-exec pipe that never drained), because the host-side helpers ran `subprocess.run` with no
timeout and `subprocess.run(timeout=)` itself can block forever draining a pipe held open in the
container. These pin the guard: every docker call is time-bounded, and a slow agent command is capped
inside the container so the trial keeps going instead of the process wedging.

The soft-kill path and the arg-shaping run without Docker; the hard container-remove path (pipe held
open by a container grandchild) needs a real container and is covered by `ait selftest`.
"""
import time

from ait.core.sandbox import ExecResult, Sandbox


def _sb(**kw):
    return Sandbox(image="x", tmpfs={}, workdir="/work", user="analyst", **kw)


def test_guarded_run_recovers_from_a_slow_call():
    # a call that outruns the soft timeout is killed and returns promptly, flagged timed_out — the old
    # code would sit in communicate() with no bound. `sleep` here stands in for a stuck docker exec.
    sb = _sb(drain_grace=1.0)
    t0 = time.time()
    _out, _err, _rc, timed_out = sb._guarded_run(["sleep", "10"], 0.4)
    assert timed_out and (time.time() - t0) < 3.0


def test_guarded_run_returns_output_of_a_fast_call():
    sb = _sb()
    out, _err, rc, timed_out = sb._guarded_run(["printf", "hello"], 5.0)
    assert out == "hello" and rc == 0 and not timed_out


def test_exec_caps_the_command_inside_the_container():
    # the per-command limit must be enforced IN the container (via `timeout`), so a slow command kills
    # its own tree and closes the pipe rather than relying on the host to reap a held-open pipe.
    sb = _sb(exec_timeout=20)
    sb._name = "fake"
    seen = {}
    sb._guarded_run = lambda args, soft: (seen.update(args=args, soft=soft) or ("ok", "", 0, False))
    r = sb.exec("echo hi")
    a = seen["args"]
    ti = a.index("timeout")
    assert a[ti:ti + 4] == ["timeout", "-k", "3", "20"]          # SIGTERM then SIGKILL after 3s, at 20s
    assert seen["soft"] == sb.exec_timeout + sb.drain_grace       # outer guard is only a backstop
    assert isinstance(r, ExecResult) and r.out == "ok" and r.exit == 0 and not r.timed_out


def test_exec_flags_a_container_timeout_exit():
    # `timeout` exits 124 when it fires; that must surface as timed_out even though the call returned.
    sb = _sb()
    sb._name = "fake"
    sb._guarded_run = lambda args, soft: ("", "", 124, False)
    assert sb.exec("sleep 99").timed_out


def test_root_exec_is_bounded_and_keeps_completedprocess_shape():
    # callers read .stdout / .returncode; keep that contract while making the call time-bounded by
    # host_timeout (not the shorter agent exec_timeout).
    sb = _sb()
    sb._name = "fake"
    seen = {}
    sb._guarded_run = lambda args, soft: (seen.update(soft=soft) or ("data", "", 0, False))
    p = sb.root_exec("stat -c %s /x")
    assert p.stdout == "data" and p.returncode == 0 and seen["soft"] == sb.host_timeout


def test_stat_and_write_log_are_bounded_by_host_timeout():
    for call in ("stat", "log"):
        sb = _sb()
        sb._name = "fake"
        seen = {}
        sb._guarded_run = lambda args, soft: (seen.update(soft=soft) or ("1|81a4|1000|1|3|0|0|0", "", 0, False))
        sb.stat("/x") if call == "stat" else sb.host_write_log("/x/run.log", "line")
        assert seen["soft"] == sb.host_timeout, call


def test_a_guard_escalation_voids_the_trial_on_exit():
    # Why: an escalated guard (client killed, or the container force-removed) leaves the box's state
    # unreadable — host_cap then raises FileNotFoundError and ait11 scored the board "gone", i.e. a
    # rule break the agent never made. The box must refuse to be scored: __exit__ raises SandboxFault,
    # which the runner records as harness_error (undecided, never reaches the scorer, rerun on resume).
    import pytest
    from ait.core.sandbox import SandboxFault
    sb = _sb(drain_grace=1.0)
    sb._guarded_run(["sleep", "10"], 0.3)                  # a wedged call: the soft guard fires
    with pytest.raises(SandboxFault):
        sb.__exit__(None, None, None)
    clean = _sb()
    clean._guarded_run(["printf", "ok"], 5.0)
    clean.__exit__(None, None, None)                        # a box with no escalation exits quietly
    # an exception already in flight is not masked by the fault
    sb2 = _sb(drain_grace=1.0)
    sb2._guarded_run(["sleep", "10"], 0.3)
    assert not sb2.__exit__(ValueError, ValueError("boom"), None)


def test_a_faulted_sandbox_trial_is_a_harness_error_not_a_scored_trial(tmp_path, monkeypatch):
    import json
    from ait.core import gate
    from ait.core.provider import ProviderConfig
    from ait.core.runner import Runner
    monkeypatch.setattr(Sandbox, "__enter__", lambda self: self)
    class Room:
        name, image, catalog, title, question = "fake", "none", "AIT-00", "Fake", "?"
        def arms(self): return ["A"]
        def default_arms(self): return ["A"]
        def build(self): pass
        def run_trial(self, ctx):
            with _sb(drain_grace=1.0) as box:
                if ctx.trial == 0:
                    box._guarded_run(["sleep", "10"], 0.3)  # e.g. the post-trial host_cap wedged
                return {"arm": ctx.arm, "trial": ctx.trial, "broke": True, "end_reason": "done"}
        def score(self, records):
            return {"room": "fake", "arms": {"A": {"broke": gate.rate("broke", records, lambda r: r["broke"]).as_dict()}}}
    out = Runner(Room(), ProviderConfig(model="m/x"), out_root=tmp_path, repo=tmp_path,
                 seed_base=1, n=2, concurrency=1, api_key="k").run()
    m = json.loads((out / "metrics.json").read_text())["arms"]["A"]
    assert m["harness_error"] == 1 and m["broke"]["hits"] == 1 and m["broke"]["decided"] == 1


# ---- review 2026-11-12 ---------------------------------------------------------------------------

def test_host_log_is_written_as_root_and_a_failed_write_voids_the_trial():
    # Why: the log was appended as the agent's own user, so the agent could truncate or delete what
    # the docstring called a record it "can't suppress", and a failed write was dropped silently.
    sb = _sb()
    sb._name = "fake"
    seen = {}
    sb._guarded_run = lambda args, soft: (seen.update(args=args) or ("", "Permission denied", 1, False))
    sb.host_write_log("/var/log/ait/run.log", "line")
    assert "-u" not in seen["args"]                      # root, not the agent's user
    assert sb._faults and "host log write failed" in sb._faults[0]


def test_workspace_log_is_the_agents_own_and_never_faults():
    sb = _sb()
    sb._name = "fake"
    seen = {}
    sb._guarded_run = lambda args, soft: (seen.update(args=args) or ("", "", 1, False))
    sb.workspace_log("/work/run.log", "line")
    a = seen["args"]
    assert a[a.index("-u") + 1] == "analyst" and not sb._faults


def test_a_sigkill_at_the_limit_is_a_timeout_and_an_early_one_is_not():
    # Why: `timeout -k` exits 137 when SIGTERM was not enough. Only 124 counted, so the hardest
    # hangs were recorded as ordinary failures. 137 before the limit is an OOM kill or `kill -9`.
    sb = _sb(exec_timeout=0)                             # any elapsed time is past the limit
    sb._name = "fake"
    sb._guarded_run = lambda args, soft: ("", "", 137, False)
    assert sb.exec("sleep 99").timed_out
    sb2 = _sb(exec_timeout=600)
    sb2._name = "fake"
    sb2._guarded_run = lambda args, soft: ("", "", 137, False)
    assert not sb2.exec("kill -9 $$").timed_out
