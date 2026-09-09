"""Assert the declared order of pipeline stages, without the real dataset.

This does not run the pipeline (that needs the 161 MB OSHA catalog and, for
the metrics stage, several minutes). It inspects ``run_pipeline``'s source to
confirm the three added stages (metrics, covariate-adjusted count models,
reconciliation) are wired in after the original five stages, and specifically
that the covariate-adjusted count-model stage is called after the figures are
written - it rewrites ``fig04_count_model_fit.svg`` last, and if it ran before
``make_figures`` the intercept-only stage would silently overwrite it again.
"""

from __future__ import annotations

import inspect
import unittest

import _context  # noqa: F401

from ehs_osha import pipeline


class TestPipelineStageOrder(unittest.TestCase):
    """The declared call order in ``run_pipeline`` must keep fig04 correct."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = inspect.getsource(pipeline.run_pipeline)

    def _index_of(self, needle: str) -> int:
        idx = self.source.find(needle)
        self.assertGreater(
            idx, -1, f"expected to find {needle!r} in run_pipeline's source"
        )
        return idx

    def test_count_models_precedes_covariate_stage(self) -> None:
        i_intercept = self._index_of("stage_count_models(")
        i_covariate = self._index_of("stage_count_models_covariates(")
        self.assertLess(
            i_intercept,
            i_covariate,
            "stage_count_models (intercept-only) must run before "
            "stage_count_models_covariates, or fig04 ends up as the "
            "intercept-only version",
        )

    def test_figures_are_made_before_covariate_stage_can_overwrite_fig04(self) -> None:
        # make_figures writes the intercept-only fig04; the covariate stage
        # must run afterwards so its fig04 write is the one left on disk.
        i_figures = self._index_of("make_figures(")
        i_covariate = self._index_of("stage_count_models_covariates(")
        self.assertLess(
            i_figures,
            i_covariate,
            "make_figures (writes the intercept-only fig04) must run before "
            "stage_count_models_covariates (rewrites fig04 with covariates), "
            "otherwise the intercept-only figure silently overwrites the "
            "covariate one",
        )

    def test_new_stages_run_after_all_original_five(self) -> None:
        original_calls = [
            "load_ita_300a(",
            "stage_quality(",
            "stage_peers(",
            "stage_count_models(",
            "stage_stability(",
        ]
        new_calls = [
            "stage_metrics(",
            "stage_count_models_covariates(",
            "stage_reconcile(",
        ]
        last_original = max(self._index_of(c) for c in original_calls)
        first_new = min(self._index_of(c) for c in new_calls)
        self.assertLess(
            last_original,
            first_new,
            "the three added stages must run after every original stage",
        )

    def test_new_stages_declared_in_metrics_then_covariates_then_reconcile_order(
        self,
    ) -> None:
        i_metrics = self._index_of("stage_metrics(")
        i_covariates = self._index_of("stage_count_models_covariates(")
        i_reconcile = self._index_of("stage_reconcile(")
        self.assertLess(i_metrics, i_covariates)
        self.assertLess(i_covariates, i_reconcile)

    def test_each_new_stage_is_individually_skippable(self) -> None:
        cfg_fields = {f.name for f in pipeline.PipelineConfig.__dataclass_fields__.values()}
        for flag in ("skip_metrics", "skip_count_models_covariates", "skip_reconcile"):
            self.assertIn(flag, cfg_fields)
            # And each flag must actually be checked in run_pipeline, not just
            # declared and ignored.
            self.assertIn(f"cfg.{flag}", self.source)


if __name__ == "__main__":
    unittest.main()
