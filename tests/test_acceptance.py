"""Regression checks for acceptance logs without requiring a benchmark environment."""
import ast
import contextlib
import glob
import io
import os
from pathlib import Path
import re
import tempfile
import time
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "run_perf.py"


def helpers():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    names = {"_acceptance_log_glob", "_resolve_acceptance_logs",
             "_acceptance_offsets", "_collect_acceptance"}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    ns = dict(glob=glob, os=os, re=re, time=time,
              ACCEPTANCE_LOG_GLOB="", ACCEPTANCE_LOG_GLOB_OVERRIDE=None,
              ACCEPTANCE_SETTLE_SECONDS=0, ACCEPTANCE_MAX_WAIT_SECONDS=0)
    # Load the real regex assignments, without running environment setup.
    nodes += [n for n in tree.body if isinstance(n, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id in {"_ACCEPTED_RE", "_PROPOSED_RE"}
                      for t in n.targets)]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), ns)
    return ns


def record(accepted, proposed):
    return "speculative_accepted_tokens: {}, speculative_proposed_tokens: {}\n".format(
        accepted, proposed)


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.ns = helpers()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = Path(self.tmp.name) / "rank_0.log"
        self.log.write_text("", encoding="utf-8")

    def collect(self, text, expected=None):
        self.log.write_text(text, encoding="utf-8")
        return self.ns["_collect_acceptance"]({str(self.log): 0}, expected)

    def test_token_weighted_not_request_mean(self):
        # Request means would give 50%; token weighting gives 10%.
        self.assertEqual(self.collect(record(1, 1) + record(0, 9)), (10.0, 2))

    def test_excludes_history(self):
        self.log.write_text(record(0, 100), encoding="utf-8")
        offsets = self.ns["_acceptance_offsets"]([str(self.log)])
        with self.log.open("a", encoding="utf-8") as f:
            f.write(record(9, 10))
        self.assertEqual(self.ns["_collect_acceptance"](offsets), (90.0, 1))

    def test_no_rate_fallback_or_partial_invalid_record(self):
        text = ("speculative_token_acceptance_rate: 0.9\n" +
                record(2, 1) + record(1, 2).rstrip("\n"))
        self.assertEqual(self.collect(text), (None, 0))
        self.assertEqual(self.collect(record(0, 0)), (None, 1))

    def test_directory_only_reads_rank_zero(self):
        other = Path(self.tmp.name) / "rank_1.log"
        other.write_text(record(0, 10), encoding="utf-8")
        self.ns["ACCEPTANCE_LOG_GLOB_OVERRIDE"] = self.tmp.name
        self.assertEqual(self.ns["_resolve_acceptance_logs"](),
                         [os.path.realpath(self.log)])

    def test_glob_selects_one_and_warns(self):
        other = Path(self.tmp.name) / "rank_1.log"
        other.write_text(record(1, 1), encoding="utf-8")
        os.utime(other, (2000000000, 2000000000))
        self.ns["ACCEPTANCE_LOG_GLOB_OVERRIDE"] = str(Path(self.tmp.name) / "*.log")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            paths = self.ns["_resolve_acceptance_logs"]()
        self.assertEqual(paths, [os.path.realpath(other)])
        self.assertTrue(out.getvalue())

    def test_delayed_flush_is_polled(self):
        log = self.log
        class Clock:
            now = 0
            @classmethod
            def monotonic(cls):
                return cls.now
            @classmethod
            def sleep(cls, seconds):
                cls.now += seconds
                log.write_text(record(3, 4), encoding="utf-8")
        self.ns["time"] = Clock
        self.ns["ACCEPTANCE_MAX_WAIT_SECONDS"] = 3
        self.assertEqual(self.collect("", 1), (75.0, 1))
        self.assertGreater(Clock.now, 0)

    def test_timeout_and_excess_records_warn(self):
        for text, expected in [("", 2), (record(1, 2)*2, 1)]:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.collect(text, expected)
            self.assertTrue(out.getvalue())

    def test_truncated_log(self):
        self.log.write_text(record(0, 100)*10, encoding="utf-8")
        offsets = self.ns["_acceptance_offsets"]([str(self.log)])
        self.log.write_text(record(1, 2), encoding="utf-8")
        self.assertEqual(self.ns["_collect_acceptance"](offsets), (50.0, 1))


if __name__ == "__main__":
    unittest.main()
