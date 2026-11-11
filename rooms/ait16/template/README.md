# __PKG__

__PURPOSE__

Input is JSONL, one __REC__ per line: `{"id": ..., "score": ..., "__NOTE__": ...}`.
A __REC__ is flagged as __FLAG__ when its score crosses the threshold.

Modules: `loader.py` (loading), `rules.py` (flagging and rates), `export.py` (rows for the report),
`fetch.py` (pulling batches from the store).

Run the tests with `python3 -m unittest discover -s tests`.
