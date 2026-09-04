"""Tests for the SVG figure writer.

Figures are part of the deliverable, so they are tested like code: the output
must be well-formed XML, must escape text, and must place data where the scaling
functions say it goes.
"""

from __future__ import annotations

import tempfile
import unittest
import xml.dom.minidom
from pathlib import Path

import _context  # noqa: F401

from ehs_osha.svgplot import Axes, Figure, autoscale, _nice_ticks


class TestAxes(unittest.TestCase):
    """Scaling must map data limits onto the plot rectangle."""

    def test_linear_scaling_endpoints(self) -> None:
        ax = Axes(xlim=(0.0, 10.0), ylim=(0.0, 100.0))
        self.assertAlmostEqual(ax.sx(0.0), ax.plot_left)
        self.assertAlmostEqual(ax.sx(10.0), ax.plot_right)
        self.assertAlmostEqual(ax.sy(0.0), ax.plot_bottom)
        self.assertAlmostEqual(ax.sy(100.0), ax.plot_top)

    def test_y_axis_is_inverted_relative_to_pixels(self) -> None:
        ax = Axes(ylim=(0.0, 1.0))
        self.assertLess(ax.sy(1.0), ax.sy(0.0))

    def test_log_scaling(self) -> None:
        ax = Axes(ylim=(1.0, 1000.0), ylog=True)
        mid = ax.sy(10.0**1.5)
        self.assertAlmostEqual(mid, 0.5 * (ax.sy(1.0) + ax.sy(1000.0)), places=6)

    def test_degenerate_limits_do_not_divide_by_zero(self) -> None:
        ax = Axes(xlim=(5.0, 5.0), ylim=(2.0, 2.0))
        self.assertTrue(float(ax.sx(5.0)) == ax.plot_left)
        self.assertTrue(float(ax.sy(2.0)) == ax.plot_bottom)


class TestFigure(unittest.TestCase):
    """Figures must serialise to valid, safe SVG."""

    def _parse(self, svg: str) -> None:
        xml.dom.minidom.parseString(svg)

    def test_bar_chart_is_valid_xml(self) -> None:
        f = Figure("t", "x", "y", Axes(ylim=(0, 10)), "sub")
        f.bars(["a", "b", "c"], {"one": [1, 2, 3], "two": [3, 2, 1]})
        self._parse(f.to_svg())

    def test_bar_series_length_is_checked(self) -> None:
        f = Figure("t", "x", "y")
        with self.assertRaises(ValueError):
            f.bars(["a", "b"], {"s": [1.0]})

    def test_line_and_scatter_valid(self) -> None:
        f = Figure("t", "x", "y", Axes(xlim=(0, 5), ylim=(0, 5)))
        f.line([0, 1, 2], [1, 2, 3], "line")
        f.scatter([1, 2], [2, 3], "points")
        f.abline(1.0, 0.0)
        self._parse(f.to_svg(x_ticks=[0, 1, 2, 3, 4, 5]))

    def test_line_length_mismatch_raises(self) -> None:
        f = Figure("t", "x", "y")
        with self.assertRaises(ValueError):
            f.line([1, 2], [1], "bad")
        with self.assertRaises(ValueError):
            f.scatter([1, 2], [1], "bad")

    def test_non_finite_points_are_skipped_not_emitted(self) -> None:
        f = Figure("t", "x", "y", Axes(xlim=(0, 3), ylim=(0, 3)))
        f.line([0, 1, float("nan")], [0, 1, 2], "l")
        svg = f.to_svg()
        self.assertNotIn("nan", svg.lower())
        self._parse(svg)

    def test_text_is_escaped(self) -> None:
        f = Figure('Title with <tag> & "quote"', "x", "y", Axes(ylim=(0, 1)))
        f.bars(["<a>"], {"s": [0.5]})
        svg = f.to_svg()
        self.assertIn("&lt;tag&gt;", svg)
        self.assertNotIn("<tag>", svg)
        self._parse(svg)

    def test_save_writes_a_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            f = Figure("t", "x", "y", Axes(ylim=(0, 1)))
            f.bars(["a"], {"s": [0.5]})
            p = f.save(Path(td) / "sub" / "fig.svg")
            self.assertTrue(p.exists())
            self._parse(p.read_text(encoding="utf-8"))


class TestHelpers(unittest.TestCase):
    """Tick and autoscale helpers."""

    def test_nice_ticks_lie_inside_the_range(self) -> None:
        ticks = _nice_ticks(0.0, 9.7)
        self.assertTrue(all(0.0 <= t <= 9.7 for t in ticks))
        self.assertGreaterEqual(len(ticks), 3)

    def test_nice_ticks_degenerate(self) -> None:
        self.assertEqual(_nice_ticks(5.0, 5.0), [5.0, 5.0])

    def test_autoscale_pads_and_survives_nan(self) -> None:
        lo, hi = autoscale([1.0, float("nan"), 3.0])
        self.assertLess(lo, 1.0)
        self.assertGreater(hi, 3.0)
        self.assertEqual(autoscale([float("nan")]), (0.0, 1.0))
        lo2, hi2 = autoscale([2.0, 2.0])
        self.assertLess(lo2, hi2)


if __name__ == "__main__":
    unittest.main()
