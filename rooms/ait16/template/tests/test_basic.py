import json
import os
import tempfile
import unittest

from __PKG__.loader import load_records
from __PKG__.rules import is_flagged


class Basic(unittest.TestCase):
    def test_load(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
            fh.write(json.dumps({"id": "a", "score": 0.9, "__NOTE__": "x"}) + "\n")
            path = fh.name
        try:
            self.assertEqual(load_records(path)[0]["id"], "a")
        finally:
            os.unlink(path)

    def test_flag_high(self):
        self.assertTrue(is_flagged({"score": 0.9}, 0.5))


if __name__ == "__main__":
    unittest.main()
