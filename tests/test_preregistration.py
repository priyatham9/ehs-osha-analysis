"""Tests for the 2025 pre-registration: reproduction, frozen code, and scoring."""

from __future__ import annotations

import hashlib
import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import _context  # noqa: F401
import pandas as pd

ROOT = _context.ROOT
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_preregistration as ev  # noqa: E402
import preregister_2025 as pre  # noqa: E402

DOC = ROOT / "docs" / "PREREGISTRATION_2025.md"


class TestReproduction(unittest.TestCase):
    def test_rerun_reproduces_committed_csv(self) -> None:
        committed = pre.OUT_CSV.read_text(encoding="utf-8")
        self.assertEqual(committed, pre.render_csv(pre.build_predictions()))

    def test_rerun_is_deterministic(self) -> None:
        a = pre.render_csv(pre.build_predictions())
        b = pre.render_csv(pre.build_predictions())
        self.assertEqual(a, b)

    def test_doc_embeds_the_committed_table_and_script_hash(self) -> None:
        text = DOC.read_text(encoding="utf-8")
        self.assertIn(pre.render_markdown_table(pre.build_predictions()), text)
        digest = hashlib.sha256((ROOT / "scripts" / "preregister_2025.py").read_bytes()).hexdigest()
        self.assertIn(digest, text, "script changed after registration; see doc section 'Frozen code'")

    def test_doc_states_registration_date(self) -> None:
        self.assertIn("2026-10-27", DOC.read_text(encoding="utf-8"))

    def test_history_hash_matches_history_column(self) -> None:
        for r in pre.build_predictions():
            vals = [float(v) for v in r["history"].split(";")]
            self.assertEqual(pre._series_hash(vals), r["history_sha256"])
            self.assertEqual(len(vals), 9)

    def test_intervals_contain_point_prediction(self) -> None:
        for r in pre.build_predictions():
            if r["transform"] == "threshold":
                continue
            self.assertLess(float(r["lo95"]), float(r["pred"]))
            self.assertLess(float(r["pred"]), float(r["hi95"]))


class TestForecastMath(unittest.TestCase):
    def test_constant_series_has_zero_width(self) -> None:
        f = pre.forecast([2.0] * 9, "identity")
        self.assertEqual((f["pred"], f["lo95"], f["hi95"]), (2.0, 2.0, 2.0))

    def test_hand_computed_identity_case(self) -> None:
        # x = 1,2,3,4: one error: 4 - mean(1,2,3) = 2 -> rmse 2; window mean (2+3+4)/3 = 3
        f = pre.forecast([1.0, 2.0, 3.0, 4.0], "identity")
        self.assertAlmostEqual(f["pred"], 3.0)
        self.assertAlmostEqual(f["hi95"], 3.0 + pre.T_975_DF6 * 2.0)

    def test_logit_stays_in_unit_interval(self) -> None:
        f = pre.forecast([0.02, 0.03, 0.01, 0.05, 0.02, 0.04, 0.02, 0.03, 0.02], "logit")
        self.assertTrue(0.0 < f["lo95"] < f["pred"] < f["hi95"] < 1.0)

    def test_log_is_geometric_mean(self) -> None:
        f = pre.forecast([1.0, 1.0, 1.0, 4.0, 4.0, 4.0], "log")
        self.assertAlmostEqual(f["pred"], 4.0)
        self.assertTrue(math.isfinite(f["hi95"]))

    def test_only_years_up_to_2024_are_used(self) -> None:
        for spec in pre.yearly_quantities(pre.TABLES):
            self.assertEqual(spec["years"], list(range(2016, 2025)))


class TestEvaluator(unittest.TestCase):
    def _tables_with_2025(self, flagged_share: float, zero_scale: float) -> Path:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        q = pd.read_csv(pre.TABLES / "quality_by_year.csv")
        new = q.iloc[-1].copy()
        new["label"] = 2025.0
        new["implausible_share"] = flagged_share
        q = pd.concat([q, new.to_frame().T], ignore_index=True)
        q.to_csv(tmp / "quality_by_year.csv", index=False)
        p = pd.read_csv(pre.TABLES / "peer_percentiles_by_year.csv")
        last = p[p["year_filing_for"] == 2024.0].copy()
        last["year_filing_for"] = 2025.0
        last["zero_share"] = (last["zero_share"] * zero_scale).clip(upper=1.0)
        pd.concat([p, last], ignore_index=True).to_csv(tmp / "peer_percentiles_by_year.csv", index=False)
        return tmp

    def test_no_2025_rows_means_nothing_scored(self) -> None:
        self.assertEqual(ev.observed_2025(pre.TABLES), {})
        self.assertEqual(ev.main([]), 2)

    def test_scoring_held_and_not_held(self) -> None:
        preds = ev.load_predictions()
        pred = {r["id"]: float(r["pred"]) for r in preds}
        tmp = self._tables_with_2025(flagged_share=pred["Q1"], zero_scale=1.0)
        res = {x["id"]: x for x in ev.score(preds, ev.observed_2025(tmp))}
        self.assertEqual(res["Q1"]["verdict"], "held")
        self.assertEqual(res["Q5"]["verdict"], "held")
        tmp2 = self._tables_with_2025(flagged_share=0.5, zero_scale=1.0)
        res2 = {x["id"]: x for x in ev.score(preds, ev.observed_2025(tmp2))}
        self.assertEqual(res2["Q1"]["verdict"], "not held")

    def test_boundary_is_inclusive_and_threshold_is_strict(self) -> None:
        preds = ev.load_predictions()
        q1 = next(r for r in preds if r["id"] == "Q1")
        lo = float(q1["lo95"])
        res = ev.score([q1], {"Q1": lo})
        self.assertEqual(res[0]["verdict"], "held")
        q5 = next(r for r in preds if r["id"] == "Q5")
        self.assertEqual(ev.score([q5], {"Q5": 1.0})[0]["verdict"], "not held")
        self.assertEqual(ev.score([q5], {"Q5": 1.01})[0]["verdict"], "held")

    def test_missing_observation_is_not_evaluable(self) -> None:
        preds = ev.load_predictions()
        self.assertTrue(all(x["verdict"] == "not evaluable" for x in ev.score(preds, {})))


if __name__ == "__main__":
    unittest.main()
