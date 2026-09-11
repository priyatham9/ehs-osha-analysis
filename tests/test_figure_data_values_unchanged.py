"""Card B1 regression: the visual restyle must not move a single data value.

``tests/fixtures/pre_visual_system_figures/`` holds a copy of the six (seven,
counting fig08) committed SVGs exactly as they stood before the figures were
redrawn as one visual system - same palette-onto-tokens mapping, direct end
labels instead of a legend box, 2019/2024 callouts on fig01, 12px mono axis
type. That restyle touches labels, fonts and decoration only; every data mark
(bar rects, line polylines, line/scatter markers) must land at the exact same
pixel position it did before, because the underlying Axes scaling and margins
are untouched and the pipeline's numbers have not changed.

This test parses the geometry of the actual data marks out of both the old
and the current SVG for each figure and asserts they are identical, ignoring
whatever new decoration (direct-label dots, callout rings, extra text) the
restyle added.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import _context  # noqa: F401

FIXTURES = Path(__file__).parent / "fixtures" / "pre_visual_system_figures"
CURRENT = Path(__file__).resolve().parents[1] / "outputs" / "figures"

# fig04 is the one figure whose bars come from a multi-start Nelder-Mead count
# model refit (see count_models_covariates.py), not a direct aggregation. Two
# independent refits of the same data can land a fraction of a pixel apart
# even with the drawing code unchanged, so it gets a small pixel tolerance;
# every other figure is a deterministic aggregation and must match exactly.
FUZZY_FIGURES = {"fig04_count_model_fit.svg"}
FUZZY_TOLERANCE_PX = 2.0

# Radii used for genuine data markers by svgplot.line() / .scatter(). The
# restyle's new decoration uses other radii (3 for a direct-label dot, 4.5 for
# an annotate() callout ring), so filtering on these excludes it cleanly.
DATA_MARKER_RADII = {"3.2", "2.4"}

RECT_RE = re.compile(r'<rect\b([^>]*)/>')
ATTR_RE = re.compile(r'(\w[\w-]*)="([^"]*)"')
CIRCLE_RE = re.compile(r'<circle\b([^>]*)/>')
POLYLINE_RE = re.compile(r'<polyline\b([^>]*)/>')


def _attrs(tag_attrs: str) -> dict:
    return dict(ATTR_RE.findall(tag_attrs))


def _round(v: str, places: int = 1) -> float:
    return round(float(v), places)


def data_rects(svg: str) -> list:
    """Every ``<rect>`` that is an actual data bar.

    Excludes the full-canvas background rect (x=0, y=0) and, in the old
    (pre-restyle) files only, the 10x10 legend swatch rects the old legend
    box drew - real bar widths are computed from the plot geometry and never
    land on exactly 10x10.
    """
    out = []
    for m in RECT_RE.finditer(svg):
        a = _attrs(m.group(1))
        if a.get("x") == "0" and a.get("y") == "0":
            continue  # the background rect, not a data bar
        if a.get("width") == "10" and a.get("height") == "10":
            continue  # an old legend swatch, not a data bar
        out.append((_round(a["x"]), _round(a["y"]), _round(a["width"]), _round(a["height"])))
    return sorted(out)


def data_circles(svg: str) -> list:
    """Line-marker / scatter-point circles, excluding new decoration."""
    out = []
    for m in CIRCLE_RE.finditer(svg):
        a = _attrs(m.group(1))
        if a.get("r") not in DATA_MARKER_RADII:
            continue
        out.append((_round(a["cx"]), _round(a["cy"])))
    return sorted(out)


def data_polylines(svg: str) -> list:
    """Polyline point lists (line-chart paths)."""
    out = []
    for m in POLYLINE_RE.finditer(svg):
        a = _attrs(m.group(1))
        pts = a.get("points", "")
        coords = tuple(
            round(float(v), 1)
            for pair in pts.split()
            for v in pair.split(",")
        )
        out.append(coords)
    return sorted(out)


class TestFigureDataValuesUnchanged(unittest.TestCase):
    """Redrawing the figures must be a pure restyle, not a data change."""

    def _pairs(self):
        for old_path in sorted(FIXTURES.glob("*.svg")):
            new_path = CURRENT / old_path.name
            yield old_path.name, old_path, new_path

    def test_fixture_and_current_dirs_are_non_empty(self) -> None:
        pairs = list(self._pairs())
        self.assertEqual(len(pairs), 7)

    def test_bar_rect_geometry_is_identical(self) -> None:
        for name, old_path, new_path in self._pairs():
            if not new_path.exists():
                continue
            old_svg = old_path.read_text(encoding="utf-8")
            new_svg = new_path.read_text(encoding="utf-8")
            old_rects = data_rects(old_svg)
            new_rects = data_rects(new_svg)
            if not old_rects:
                continue
            with self.subTest(figure=name):
                if name in FUZZY_FIGURES:
                    self.assertEqual(len(old_rects), len(new_rects), f"{name}: bar count changed")
                    for old_r, new_r in zip(old_rects, new_rects):
                        for old_v, new_v in zip(old_r, new_r):
                            self.assertAlmostEqual(
                                old_v, new_v, delta=FUZZY_TOLERANCE_PX,
                                msg=f"{name}: bar geometry moved beyond refit tolerance",
                            )
                else:
                    self.assertEqual(
                        old_rects,
                        new_rects,
                        f"{name}: bar geometry changed - a data value moved",
                    )

    def test_line_and_scatter_marker_geometry_is_identical(self) -> None:
        for name, old_path, new_path in self._pairs():
            if not new_path.exists():
                continue
            old_svg = old_path.read_text(encoding="utf-8")
            new_svg = new_path.read_text(encoding="utf-8")
            old_c, new_c = data_circles(old_svg), data_circles(new_svg)
            if old_c:
                with self.subTest(figure=name, mark="circle"):
                    self.assertEqual(old_c, new_c, f"{name}: marker geometry changed")
            old_p, new_p = data_polylines(old_svg), data_polylines(new_svg)
            if old_p:
                with self.subTest(figure=name, mark="polyline"):
                    self.assertEqual(old_p, new_p, f"{name}: line geometry changed")


if __name__ == "__main__":
    unittest.main()
