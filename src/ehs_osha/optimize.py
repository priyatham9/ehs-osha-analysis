"""Minimal derivative-free optimisation, implemented here because SciPy is not
an allowed dependency for this project.

Contains a Nelder-Mead simplex minimiser (Nelder & Mead 1965) with the standard
reflection / expansion / contraction / shrink steps, and a golden-section line
search for one-dimensional problems. Both are used only for low-dimensional
maximum-likelihood problems (1-3 free parameters), where Nelder-Mead is
reliable and its lack of derivative information costs little.

Parameters are always optimised on an unconstrained scale (log for positive
quantities, logit for probabilities); the model modules do the transforms. That
keeps the simplex from wandering into invalid regions and removes the need for
constraint handling here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Sequence, Tuple

import numpy as np


@dataclass
class OptimizeResult:
    """Outcome of a minimisation.

    Attributes:
        x: Best parameter vector found.
        fun: Objective value at ``x``.
        nit: Iterations performed.
        nfev: Objective evaluations.
        converged: Whether both the simplex spread and the function spread fell
            below tolerance before the iteration cap.
        message: Human-readable status.
    """

    x: np.ndarray
    fun: float
    nit: int
    nfev: int
    converged: bool
    message: str


def nelder_mead(
    func: Callable[[np.ndarray], float],
    x0: Sequence[float],
    *,
    step: float = 0.5,
    xtol: float = 1e-8,
    ftol: float = 1e-10,
    max_iter: int = 5000,
    initial_simplex: Optional[np.ndarray] = None,
) -> OptimizeResult:
    """Minimise ``func`` by the Nelder-Mead simplex method.

    Args:
        func: Objective returning a finite float, or ``inf`` for invalid input.
        x0: Starting point, length ``n``.
        step: Offset used to build the initial simplex when one is not given.
        xtol: Convergence tolerance on the simplex diameter.
        ftol: Convergence tolerance on the spread of objective values.
        max_iter: Iteration cap.
        initial_simplex: Optional ``(n+1, n)`` starting simplex.

    Returns:
        An :class:`OptimizeResult`.

    Raises:
        ValueError: If ``x0`` is empty or ``initial_simplex`` has a bad shape.
    """
    x0 = np.asarray(x0, dtype="float64")
    n = x0.size
    if n == 0:
        raise ValueError("x0 must have at least one element")

    if initial_simplex is None:
        sim = np.repeat(x0[None, :], n + 1, axis=0)
        for i in range(n):
            sim[i + 1, i] += step if x0[i] == 0 else step * max(1.0, abs(x0[i]))
    else:
        sim = np.asarray(initial_simplex, dtype="float64")
        if sim.shape != (n + 1, n):
            raise ValueError(f"initial_simplex must have shape {(n + 1, n)}")

    nfev = 0

    def f(v: np.ndarray) -> float:
        nonlocal nfev
        nfev += 1
        try:
            val = float(func(v))
        except (FloatingPointError, OverflowError, ValueError):
            return float("inf")
        return val if np.isfinite(val) else float("inf")

    fv = np.array([f(p) for p in sim], dtype="float64")
    alpha, gamma, rho, sigma = 1.0, 2.0, 0.5, 0.5

    it = 0
    converged = False
    for it in range(1, max_iter + 1):
        order = np.argsort(fv, kind="mergesort")
        sim, fv = sim[order], fv[order]

        spread_x = float(np.max(np.abs(sim[1:] - sim[0])))
        finite = fv[np.isfinite(fv)]
        spread_f = float(np.max(finite) - np.min(finite)) if finite.size > 1 else 0.0
        if spread_x <= xtol and spread_f <= ftol:
            converged = True
            break

        centroid = sim[:-1].mean(axis=0)
        xr = centroid + alpha * (centroid - sim[-1])
        fr = f(xr)

        if fr < fv[0]:
            xe = centroid + gamma * (xr - centroid)
            fe = f(xe)
            sim[-1], fv[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < fv[-2]:
            sim[-1], fv[-1] = xr, fr
        else:
            if fr < fv[-1]:
                xc = centroid + rho * (xr - centroid)
                fc = f(xc)
                if fc <= fr:
                    sim[-1], fv[-1] = xc, fc
                    continue
            else:
                xc = centroid + rho * (sim[-1] - centroid)
                fc = f(xc)
                if fc < fv[-1]:
                    sim[-1], fv[-1] = xc, fc
                    continue
            sim[1:] = sim[0] + sigma * (sim[1:] - sim[0])
            for i in range(1, n + 1):
                fv[i] = f(sim[i])

    best = int(np.argmin(fv))
    return OptimizeResult(
        x=sim[best].copy(),
        fun=float(fv[best]),
        nit=it,
        nfev=nfev,
        converged=converged,
        message="converged" if converged else "iteration limit reached",
    )


def golden_section(
    func: Callable[[float], float],
    lo: float,
    hi: float,
    *,
    tol: float = 1e-8,
    max_iter: int = 500,
) -> Tuple[float, float]:
    """Minimise a unimodal 1-D function on ``[lo, hi]`` by golden-section search.

    Args:
        func: Scalar objective.
        lo: Lower bracket.
        hi: Upper bracket.
        tol: Absolute tolerance on the bracket width.
        max_iter: Iteration cap.

    Returns:
        ``(x, f(x))`` at the located minimum.

    Raises:
        ValueError: If ``hi <= lo``.
    """
    if hi <= lo:
        raise ValueError("hi must exceed lo")
    invphi = (np.sqrt(5.0) - 1.0) / 2.0
    a, b = float(lo), float(hi)
    c, d = b - invphi * (b - a), a + invphi * (b - a)
    fc, fd = func(c), func(d)
    for _ in range(max_iter):
        if abs(b - a) < tol:
            break
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - invphi * (b - a)
            fc = func(c)
        else:
            a, c, fc = c, d, fd
            d = a + invphi * (b - a)
            fd = func(d)
    x = 0.5 * (a + b)
    return x, func(x)


def multistart_nelder_mead(
    func: Callable[[np.ndarray], float],
    starts: Sequence[Sequence[float]],
    **kwargs,
) -> OptimizeResult:
    """Run :func:`nelder_mead` from several starting points and keep the best.

    Likelihoods for zero-inflated models are not always unimodal in the
    parameters, so a single start is not enough to claim a global optimum. This
    does not guarantee one either, but it makes a local trap far less likely and
    the spread across starts is a usable diagnostic.

    Args:
        func: Objective to minimise.
        starts: Starting points.
        **kwargs: Passed through to :func:`nelder_mead`.

    Returns:
        The best :class:`OptimizeResult` across starts.

    Raises:
        ValueError: If ``starts`` is empty.
    """
    if not len(starts):
        raise ValueError("at least one starting point is required")
    best: Optional[OptimizeResult] = None
    total_nfev = 0
    for s in starts:
        res = nelder_mead(func, s, **kwargs)
        total_nfev += res.nfev
        if best is None or res.fun < best.fun:
            best = res
    assert best is not None
    best.nfev = total_nfev
    return best
