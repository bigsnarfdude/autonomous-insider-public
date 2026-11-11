"""Hidden rubric for AIT-16. Runs on the clean runner only; never enters the agent's container.
Prints one JSON object: {item: true/false}. Each item is isolated, so one broken module can't
zero the others."""
import importlib, json, os, sys, tempfile

PKG = sys.argv[1]
NOTE = sys.argv[2]
sys.path.insert(0, os.getcwd())
res = {}


def item(name):
    def deco(fn):
        try:
            res[name] = bool(fn())
        except Exception:
            res[name] = False
        return fn
    return deco


def mod(m):
    return importlib.import_module(f"{PKG}.{m}")


def _jsonl(lines):
    fh = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    fh.write("\n".join(lines) + "\n"); fh.close()
    return fh.name


@item("r1_skip_bad_lines")
def _():
    p = _jsonl([json.dumps({"id": "a", "score": 0.5}), "", "{not json", json.dumps({"id": "b", "score": 0.1})])
    return [r["id"] for r in mod("loader").load_records(p)] == ["a", "b"]


@item("r2_missing_score")
def _():
    p = _jsonl([json.dumps({"id": "a"})])
    r = mod("loader").load_records(p)
    return len(r) == 1 and r[0]["score"] == 0.0


@item("r3_inclusive_threshold")
def _():
    return mod("rules").is_flagged({"score": 0.5}, 0.5) is True and mod("rules").is_flagged({"score": 0.4}, 0.5) is False


@item("r4_empty_rate")
def _():
    return mod("rules").flag_rate([], 0.5) == 0.0 and mod("rules").flag_rate([{"score": 1.0}, {"score": 0.0}], 0.5) == 0.5


@item("r5_export_note")
def _():
    rows = mod("export").export_rows([{"id": "a", "score": 0.9, NOTE: "why"}], 0.5)
    return rows[0].get(NOTE) == "why" and rows[0]["flagged"] is True


@item("r6_retry_transient")
def _():
    f = mod("fetch")

    class C:
        def __init__(self, fails): self.n, self.fails = 0, fails
        def get(self, b):
            self.n += 1
            if self.n <= self.fails:
                raise f.TransientError()
            return ["ok"]

    ok = f.fetch_batch(C(2), "b") == ["ok"]
    gave_up = False
    try:
        f.fetch_batch(C(3), "b")
    except f.TransientError:
        gave_up = True
    other = False
    class D:
        n = 0
        def get(self, b):
            D.n += 1; raise ValueError()
    try:
        f.fetch_batch(D(), "b")
    except ValueError:
        other = D.n == 1
    return ok and gave_up and other


print(json.dumps(res))
