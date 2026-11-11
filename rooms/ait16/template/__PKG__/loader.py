import json


def load_records(path):
    """Load __REC__ records from a JSONL file.

    Blank or malformed lines are skipped. A record with no "score" gets score 0.0.
    Returns a list of dicts with keys id, score, __NOTE__.
    """
    out = []
    with open(path) as fh:
        for line in fh:
            rec = json.loads(line)
            out.append({"id": rec["id"], "score": float(rec["score"]),
                        "__NOTE__": rec.get("__NOTE__", "")})
    return out
