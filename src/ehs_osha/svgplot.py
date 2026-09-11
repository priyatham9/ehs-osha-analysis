"""A very small SVG chart writer.

matplotlib is not an allowed dependency for this project, so figures are emitted
as hand-written SVG. The scope is deliberately narrow: grouped bar charts, line
charts and scatter plots with linear or log axes, enough to render the figures
this analysis needs and nothing more.

Every figure in ``outputs/figures`` is produced by a call into this module from
:mod:`ehs_osha.pipeline`. No figure is drawn by hand or edited after generation.
"""

from __future__ import annotations

import html
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

#: Colour-blind-safe qualitative palette (Okabe & Ito 2008).
PALETTE: Tuple[str, ...] = (
    "#0072B2",
    "#D55E00",
    "#009E73",
    "#CC79A7",
    "#E69F00",
    "#56B4E9",
    "#332288",
)

_FONT = "'IBM Plex Mono', ui-monospace, 'SF Mono', Menlo, Consolas, monospace"


@dataclass
class Axes:
    """Plot geometry and scaling.

    Attributes:
        width: Total SVG width in px.
        height: Total SVG height in px.
        margin: ``(left, right, top, bottom)`` margins in px.
        xlim: Data limits on x.
        ylim: Data limits on y.
        ylog: Use a base-10 log scale on y.
    """

    width: int = 820
    height: int = 460
    margin: Tuple[int, int, int, int] = (78, 24, 46, 74)
    xlim: Tuple[float, float] = (0.0, 1.0)
    ylim: Tuple[float, float] = (0.0, 1.0)
    ylog: bool = False

    @property
    def plot_left(self) -> float:
        """Left edge of the plotting area."""
        return self.margin[0]

    @property
    def plot_right(self) -> float:
        """Right edge of the plotting area."""
        return self.width - self.margin[1]

    @property
    def plot_top(self) -> float:
        """Top edge of the plotting area."""
        return self.margin[2]

    @property
    def plot_bottom(self) -> float:
        """Bottom edge of the plotting area."""
        return self.height - self.margin[3]

    def sx(self, x: float) -> float:
        """Map a data x value to a pixel x coordinate."""
        lo, hi = self.xlim
        span = (hi - lo) or 1.0
        return self.plot_left + (x - lo) / span * (self.plot_right - self.plot_left)

    def sy(self, y: float) -> float:
        """Map a data y value to a pixel y coordinate."""
        lo, hi = self.ylim
        if self.ylog:
            lo, hi = math.log10(max(lo, 1e-12)), math.log10(max(hi, 1e-12))
            y = math.log10(max(y, 1e-12))
        span = (hi - lo) or 1.0
        return self.plot_bottom - (y - lo) / span * (self.plot_bottom - self.plot_top)


def _esc(s: object) -> str:
    """HTML-escape a value for inclusion in SVG text."""
    return html.escape(str(s), quote=True)


def _nice_ticks(lo: float, hi: float, target: int = 6) -> List[float]:
    """Produce readable tick locations spanning ``[lo, hi]``.

    Args:
        lo: Lower limit.
        hi: Upper limit.
        target: Approximate number of ticks wanted.

    Returns:
        Tick values inside the range.
    """
    if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
        return [lo, hi]
    raw = (hi - lo) / max(target, 1)
    mag = 10 ** math.floor(math.log10(raw))
    for mult in (1, 2, 2.5, 5, 10):
        if raw <= mag * mult:
            step = mag * mult
            break
    else:  # pragma: no cover - unreachable given the 10x branch
        step = mag * 10
    start = math.ceil(lo / step) * step
    ticks, v = [], start
    while v <= hi + step * 1e-9:
        ticks.append(round(v, 10))
        v += step
    return ticks


class Figure:
    """An SVG figure under construction.

    Args:
        title: Figure title drawn at the top.
        xlabel: X axis label.
        ylabel: Y axis label.
        axes: Geometry and scaling.
        subtitle: Optional smaller line under the title, used for provenance.
    """

    def __init__(
        self,
        title: str,
        xlabel: str,
        ylabel: str,
        axes: Optional[Axes] = None,
        subtitle: str = "",
    ) -> None:
        self.title = title
        self.subtitle = subtitle
        self.xlabel = xlabel
        self.ylabel = ylabel
        self.ax = axes or Axes()
        self._body: List[str] = []
        self._legend: List[Tuple[str, str]] = []

    def add_legend_entry(self, label: str, colour: str) -> None:
        """Register a legend entry.

        Args:
            label: Text shown in the legend.
            colour: Swatch colour.
        """
        self._legend.append((label, colour))

    def bars(
        self,
        categories: Sequence[str],
        series: Dict[str, Sequence[float]],
        *,
        colours: Optional[Sequence[str]] = None,
    ) -> "Figure":
        """Draw a grouped bar chart.

        Args:
            categories: Category labels along x.
            series: Mapping of series name to one value per category.
            colours: Explicit colours; defaults to :data:`PALETTE`.

        Returns:
            ``self``, for chaining.

        Raises:
            ValueError: If a series length does not match ``categories``.
        """
        n_cat, n_ser = len(categories), max(len(series), 1)
        for name, vals in series.items():
            if len(vals) != n_cat:
                raise ValueError(f"series {name!r} has {len(vals)} values, need {n_cat}")
        cols = list(colours or PALETTE)
        self.ax.xlim = (0.0, float(n_cat))
        slot = (self.ax.plot_right - self.ax.plot_left) / max(n_cat, 1)
        bw = slot * 0.8 / n_ser
        for si, (name, vals) in enumerate(series.items()):
            colour = cols[si % len(cols)]
            self.add_legend_entry(name, colour)
            for ci, v in enumerate(vals):
                if not math.isfinite(v):
                    continue
                x0 = self.ax.plot_left + ci * slot + slot * 0.1 + si * bw
                y1 = self.ax.sy(max(v, self.ax.ylim[0]))
                y0 = self.ax.sy(self.ax.ylim[0])
                self._body.append(
                    f'<rect x="{x0:.2f}" y="{min(y0, y1):.2f}" width="{bw:.2f}" '
                    f'height="{abs(y0 - y1):.2f}" fill="{colour}" />'
                )
            # Direct label for this series, replacing a legend box: an identity
            # dot plus the series name in ink, stacked inside the plot area's
            # top-right corner so long names never run off the canvas.
            if n_ser > 1:
                lx = self.ax.plot_right - 4
                ly = self.ax.plot_top + 11 + si * 13
                self._body.append(f'<circle cx="{lx + 8:.1f}" cy="{ly - 3.5:.1f}" r="3" fill="{colour}" />')
                self._body.append(
                    f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="10" '
                    f'text-anchor="end" fill="#333">{_esc(name)}</text>'
                )
        for ci, cat in enumerate(categories):
            x = self.ax.plot_left + (ci + 0.5) * slot
            rot = -35 if max(len(str(c)) for c in categories) > 5 else 0
            anchor = "end" if rot else "middle"
            self._body.append(
                f'<text x="{x:.1f}" y="{self.ax.plot_bottom + 16:.1f}" '
                f'font-size="12" text-anchor="{anchor}" fill="#333" '
                f'transform="rotate({rot} {x:.1f} {self.ax.plot_bottom + 16:.1f})">'
                f"{_esc(cat)}</text>"
            )
        return self

    def line(
        self,
        x: Sequence[float],
        y: Sequence[float],
        label: str,
        colour: Optional[str] = None,
        *,
        markers: bool = True,
    ) -> "Figure":
        """Draw a polyline with optional markers.

        Args:
            x: X values.
            y: Y values.
            label: Legend label.
            colour: Line colour; defaults to the next palette entry.
            markers: Draw a circle at each point.

        Returns:
            ``self``, for chaining.

        Raises:
            ValueError: If ``x`` and ``y`` differ in length.
        """
        if len(x) != len(y):
            raise ValueError("x and y must be the same length")
        colour = colour or PALETTE[len(self._legend) % len(PALETTE)]
        self.add_legend_entry(label, colour)
        pts = [
            (self.ax.sx(xi), self.ax.sy(yi))
            for xi, yi in zip(x, y)
            if math.isfinite(xi) and math.isfinite(yi)
        ]
        if pts:
            d = " ".join(f"{px:.2f},{py:.2f}" for px, py in pts)
            self._body.append(
                f'<polyline points="{d}" fill="none" stroke="{colour}" '
                f'stroke-width="2.2" stroke-linejoin="round" />'
            )
            if markers:
                for px, py in pts:
                    self._body.append(
                        f'<circle cx="{px:.2f}" cy="{py:.2f}" r="3.2" '
                        f'fill="{colour}" />'
                    )
            # Direct label at the line's end, replacing a legend box.
            if len(self._legend) > 1 or markers:
                lx, ly = pts[-1]
                self._body.append(
                    f'<text x="{lx + 8:.1f}" y="{ly + 3.5:.1f}" font-size="10" '
                    f'text-anchor="start" fill="#333">{_esc(label)}</text>'
                )
        return self

    def scatter(
        self,
        x: Sequence[float],
        y: Sequence[float],
        label: str,
        colour: Optional[str] = None,
        *,
        radius: float = 2.4,
        opacity: float = 0.55,
    ) -> "Figure":
        """Draw a scatter of points.

        Args:
            x: X values.
            y: Y values.
            label: Legend label.
            colour: Point colour.
            radius: Marker radius in px.
            opacity: Marker opacity.

        Returns:
            ``self``, for chaining.

        Raises:
            ValueError: If ``x`` and ``y`` differ in length.
        """
        if len(x) != len(y):
            raise ValueError("x and y must be the same length")
        colour = colour or PALETTE[len(self._legend) % len(PALETTE)]
        self.add_legend_entry(label, colour)
        for xi, yi in zip(x, y):
            if not (math.isfinite(xi) and math.isfinite(yi)):
                continue
            self._body.append(
                f'<circle cx="{self.ax.sx(xi):.2f}" cy="{self.ax.sy(yi):.2f}" '
                f'r="{radius}" fill="{colour}" fill-opacity="{opacity}" />'
            )
        return self

    def abline(self, slope: float = 1.0, intercept: float = 0.0) -> "Figure":
        """Draw a reference straight line clipped to the axes.

        Args:
            slope: Line slope in data units.
            intercept: Line intercept in data units.

        Returns:
            ``self``, for chaining.
        """
        x0, x1 = self.ax.xlim
        self._body.append(
            f'<line x1="{self.ax.sx(x0):.2f}" y1="{self.ax.sy(slope * x0 + intercept):.2f}" '
            f'x2="{self.ax.sx(x1):.2f}" y2="{self.ax.sy(slope * x1 + intercept):.2f}" '
            f'stroke="#888" stroke-width="1.2" stroke-dasharray="5,4" />'
        )
        return self

    def annotate(
        self,
        x: float,
        y: float,
        text: str,
        *,
        dx: float = 10.0,
        dy: float = -18.0,
    ) -> "Figure":
        """Draw a callout at a data point: a ring on the point, a leader line,
        and a text label offset from it.

        Args:
            x: Data x coordinate of the point being called out.
            y: Data y coordinate of the point being called out.
            text: Callout text, one short line.
            dx: Horizontal offset of the label from the point, in px.
            dy: Vertical offset of the label from the point, in px (negative
                is upward).

        Returns:
            ``self``, for chaining.
        """
        px, py = self.ax.sx(x), self.ax.sy(y)
        lx, ly = px + dx, py + dy
        self._body.append(
            f'<circle cx="{px:.2f}" cy="{py:.2f}" r="4.5" fill="none" '
            f'stroke="#333" stroke-width="1.3" />'
        )
        self._body.append(
            f'<line x1="{px:.2f}" y1="{py:.2f}" x2="{lx:.2f}" y2="{ly:.2f}" '
            f'stroke="#333" stroke-width="1" stroke-dasharray="2,2" />'
        )
        anchor = "start" if dx >= 0 else "end"
        self._body.append(
            f'<text x="{lx:.2f}" y="{ly:.2f}" font-size="10.5" font-weight="600" '
            f'text-anchor="{anchor}" fill="#111">{_esc(text)}</text>'
        )
        return self

    def _axis_svg(self, x_ticks: Optional[Sequence[float]]) -> List[str]:
        """Render axis lines, grid, ticks and labels."""
        ax = self.ax
        out: List[str] = [
            f'<rect x="0" y="0" width="{ax.width}" height="{ax.height}" fill="#ffffff" />'
        ]
        if ax.ylog:
            lo, hi = math.log10(max(ax.ylim[0], 1e-12)), math.log10(max(ax.ylim[1], 1e-12))
            yt = [10**e for e in range(math.floor(lo), math.ceil(hi) + 1)]
        else:
            yt = _nice_ticks(ax.ylim[0], ax.ylim[1])
        for t in yt:
            y = ax.sy(t)
            if not (ax.plot_top - 1 <= y <= ax.plot_bottom + 1):
                continue
            out.append(
                f'<line x1="{ax.plot_left}" y1="{y:.2f}" x2="{ax.plot_right}" '
                f'y2="{y:.2f}" stroke="#e6e6e6" stroke-width="1" />'
            )
            lab = f"{t:g}"
            out.append(
                f'<text x="{ax.plot_left - 8}" y="{y + 4:.2f}" font-size="12" '
                f'text-anchor="end" fill="#444">{_esc(lab)}</text>'
            )
        if x_ticks is not None:
            for t in x_ticks:
                x = ax.sx(t)
                if not (ax.plot_left - 1 <= x <= ax.plot_right + 1):
                    continue
                out.append(
                    f'<line x1="{x:.2f}" y1="{ax.plot_bottom}" x2="{x:.2f}" '
                    f'y2="{ax.plot_bottom + 4}" stroke="#666" stroke-width="1" />'
                )
                out.append(
                    f'<text x="{x:.2f}" y="{ax.plot_bottom + 17}" font-size="12" '
                    f'text-anchor="middle" fill="#444">{_esc(f"{t:g}")}</text>'
                )
        out.append(
            f'<line x1="{ax.plot_left}" y1="{ax.plot_top}" x2="{ax.plot_left}" '
            f'y2="{ax.plot_bottom}" stroke="#333" stroke-width="1.2" />'
        )
        out.append(
            f'<line x1="{ax.plot_left}" y1="{ax.plot_bottom}" x2="{ax.plot_right}" '
            f'y2="{ax.plot_bottom}" stroke="#333" stroke-width="1.2" />'
        )
        return out

    def to_svg(self, x_ticks: Optional[Sequence[float]] = None) -> str:
        """Serialise the figure to an SVG document string.

        Args:
            x_ticks: Numeric x tick locations, or ``None`` for categorical axes
                where the bar routine already drew labels.

        Returns:
            A complete standalone SVG document.
        """
        ax = self.ax
        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{ax.width}" '
            f'height="{ax.height}" viewBox="0 0 {ax.width} {ax.height}" '
            f'font-family="{_FONT}">'
        ]
        parts += self._axis_svg(x_ticks)
        parts += self._body
        parts.append(
            f'<text x="{ax.plot_left}" y="24" font-size="15" font-weight="600" '
            f'fill="#111">{_esc(self.title)}</text>'
        )
        if self.subtitle:
            parts.append(
                f'<text x="{ax.plot_left}" y="40" font-size="11" fill="#666">'
                f"{_esc(self.subtitle)}</text>"
            )
        parts.append(
            f'<text x="{(ax.plot_left + ax.plot_right) / 2:.1f}" '
            f'y="{ax.height - 12}" font-size="12" text-anchor="middle" '
            f'fill="#333">{_esc(self.xlabel)}</text>'
        )
        parts.append(
            f'<text x="16" y="{(ax.plot_top + ax.plot_bottom) / 2:.1f}" '
            f'font-size="12" text-anchor="middle" fill="#333" '
            f'transform="rotate(-90 16 {(ax.plot_top + ax.plot_bottom) / 2:.1f})">'
            f"{_esc(self.ylabel)}</text>"
        )
        # No legend box: each series carries a direct label at its own end
        # (drawn by bars()/line() into self._body already), per the one
        # visual system these figures share. self._legend is kept only as
        # bookkeeping for colour assignment.
        parts.append("</svg>")
        return "\n".join(parts)

    def save(self, path: Path, x_ticks: Optional[Sequence[float]] = None) -> Path:
        """Write the figure to disk.

        Args:
            path: Destination ``.svg`` path; parent directories are created.
            x_ticks: Passed to :meth:`to_svg`.

        Returns:
            The path written.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_svg(x_ticks), encoding="utf-8")
        return path


def autoscale(values: Iterable[float], pad: float = 0.06) -> Tuple[float, float]:
    """Compute padded ``(lo, hi)`` limits from data, ignoring non-finite values.

    Args:
        values: Data values.
        pad: Fractional padding added to each end.

    Returns:
        ``(lo, hi)``; falls back to ``(0, 1)`` if nothing is finite.
    """
    arr = np.asarray(list(values), dtype="float64")
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return (0.0, 1.0)
    lo, hi = float(arr.min()), float(arr.max())
    if lo == hi:
        return (lo - 0.5, hi + 0.5)
    span = hi - lo
    return (lo - pad * span, hi + pad * span)
