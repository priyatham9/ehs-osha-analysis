"""Intercept-only count models with an exposure offset, fitted by maximum
likelihood using only NumPy and the Python standard library.

Why these models
----------------
Establishment recordable-case counts are not Poisson. Two things are visibly
wrong with a Poisson description of the OSHA ITA data: the variance far exceeds
the mean, and there are far more zeros than a Poisson with the observed mean
would produce. Those are different problems with different implications, and
distinguishing them matters:

* **Overdispersion alone** (negative binomial) says establishments differ in
  their underlying rate. Nothing is special about zero; it is just the low end
  of a heterogeneous population.
* **Zero inflation** says some establishments are in a state where a recordable
  case is not merely unlikely but structurally absent from the record -- which
  in administrative injury data mixes genuinely incident-free operations with
  under-recording. A zero-inflated model can measure the excess but cannot
  attribute it between those two causes, and this module does not pretend
  otherwise.

Four models are provided, all intercept-only with an exposure offset:

============  =========================================================
Model         Mean structure
============  =========================================================
Poisson       ``E[y_i] = E_i * mu``
NB2           ``E[y_i] = E_i * mu``, ``Var = m + alpha * m^2``
ZIP           ``pi`` structural zeros, else Poisson
ZINB          ``pi`` structural zeros, else NB2
============  =========================================================

``E_i`` is exposure in 200,000-hour units, so ``mu`` is directly interpretable
as an incident rate on the TRIR scale.

Implementation notes
--------------------
``log Gamma`` is not in NumPy. ``math.lgamma`` is used, evaluated only on the
*unique* observed counts and then broadcast, which is both exact and fast:
recordable counts take few distinct values even in millions of rows.

Model comparison uses AIC and BIC, and the observed-versus-expected zero count.
The likelihood-ratio test of ZINB against NB2 places ``pi = 0`` on the boundary
of the parameter space, so the null distribution is a 50:50 mixture of a point
mass at 0 and chi-square with 1 df (Self & Liang 1987; Chernoff 1954); the
correct p-value is therefore half the naive one, and :func:`boundary_lrt`
computes it that way rather than using the standard chi-square tail.

The Vuong test is deliberately not implemented. Wilson (2015) shows it is not a
valid test for zero-inflation against a non-inflated parent model, since the
models are nested rather than strictly non-nested.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .optimize import OptimizeResult, multistart_nelder_mead

_LOG_MAX = 700.0  # exp overflow guard for float64


def _lgamma_vec(x: np.ndarray) -> np.ndarray:
    """Vectorised ``log Gamma`` evaluated on unique values only.

    Args:
        x: Non-negative array.

    Returns:
        ``lgamma(x)`` elementwise, same shape as ``x``.
    """
    uniq, inv = np.unique(x, return_inverse=True)
    vals = np.array([math.lgamma(float(u)) for u in uniq], dtype="float64")
    return vals[inv].reshape(x.shape)


def _softplus_inv_ok(v: float) -> bool:
    """Return True if ``v`` is a finite float safe to exponentiate."""
    return np.isfinite(v) and abs(v) < _LOG_MAX


def _logit(p: float) -> float:
    """Logit transform with clipping away from 0 and 1."""
    p = min(max(p, 1e-12), 1 - 1e-12)
    return math.log(p / (1 - p))


def _expit(z: float) -> float:
    """Inverse logit, overflow-safe."""
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-min(z, _LOG_MAX)))
    e = math.exp(max(z, -_LOG_MAX))
    return e / (1.0 + e)


def prepare_counts(
    y: np.ndarray, exposure: Optional[np.ndarray] = None
) -> Tuple[np.ndarray, np.ndarray]:
    """Validate and align a count vector and its exposure.

    Args:
        y: Non-negative integer counts.
        exposure: Positive exposure per observation. Defaults to all ones.

    Returns:
        ``(y, exposure)`` as float64 arrays with non-finite or invalid rows
        removed.

    Raises:
        ValueError: If ``y`` and ``exposure`` differ in length, or nothing
            usable remains.
    """
    y = np.asarray(y, dtype="float64").ravel()
    e = (
        np.ones_like(y)
        if exposure is None
        else np.asarray(exposure, dtype="float64").ravel()
    )
    if e.shape != y.shape:
        raise ValueError(f"exposure shape {e.shape} != y shape {y.shape}")
    ok = np.isfinite(y) & np.isfinite(e) & (y >= 0) & (e > 0)
    y, e = y[ok], e[ok]
    if y.size == 0:
        raise ValueError("no usable observations after filtering")
    if np.any(np.abs(y - np.round(y)) > 1e-9):
        raise ValueError("counts must be integers")
    return np.round(y), e


@dataclass
class CountFit:
    """A fitted intercept-only count model.

    Attributes:
        model: ``"poisson"``, ``"nb2"``, ``"zip"`` or ``"zinb"``.
        params: Natural-scale parameters (``mu``, and where applicable ``alpha``
            and ``pi``).
        loglik: Maximised log-likelihood.
        n: Observations used.
        k: Number of free parameters.
        converged: Optimiser convergence flag.
        expected_zeros: Model-implied expected number of zero counts.
        observed_zeros: Observed number of zero counts.
        optimizer: Raw optimiser result, for diagnostics.
    """

    model: str
    params: Dict[str, float]
    loglik: float
    n: int
    k: int
    converged: bool
    expected_zeros: float
    observed_zeros: int
    optimizer: Optional[OptimizeResult] = field(default=None, repr=False)

    @property
    def aic(self) -> float:
        """Akaike information criterion."""
        return 2 * self.k - 2 * self.loglik

    @property
    def bic(self) -> float:
        """Bayesian information criterion."""
        return self.k * math.log(self.n) - 2 * self.loglik

    @property
    def zero_ratio(self) -> float:
        """Observed zeros divided by model-expected zeros."""
        return (
            self.observed_zeros / self.expected_zeros
            if self.expected_zeros > 0
            else float("nan")
        )

    def to_json(self) -> dict:
        """Return a JSON-serialisable dict of this fit."""
        return {
            "model": self.model,
            "params": {k: float(v) for k, v in self.params.items()},
            "loglik": float(self.loglik),
            "n": int(self.n),
            "k": int(self.k),
            "converged": bool(self.converged),
            "aic": float(self.aic),
            "bic": float(self.bic),
            "observed_zeros": int(self.observed_zeros),
            "expected_zeros": float(self.expected_zeros),
            "zero_ratio_observed_over_expected": float(self.zero_ratio),
        }


def poisson_loglik(y: np.ndarray, m: np.ndarray) -> float:
    """Poisson log-likelihood.

    Args:
        y: Counts.
        m: Per-observation means, strictly positive.

    Returns:
        Sum of log densities, or ``-inf`` if any mean is invalid.
    """
    if np.any(~np.isfinite(m)) or np.any(m <= 0):
        return float("-inf")
    return float(np.sum(y * np.log(m) - m - _lgamma_vec(y + 1.0)))


def nb2_loglik(y: np.ndarray, m: np.ndarray, alpha: float) -> float:
    """Negative binomial (NB2) log-likelihood.

    Uses the ``r = 1/alpha`` parameterisation with
    ``Var(y) = m + alpha * m^2``.

    Args:
        y: Counts.
        m: Per-observation means, strictly positive.
        alpha: Dispersion parameter, strictly positive.

    Returns:
        Sum of log densities, or ``-inf`` on invalid input.
    """
    if not np.isfinite(alpha) or alpha <= 0:
        return float("-inf")
    if np.any(~np.isfinite(m)) or np.any(m <= 0):
        return float("-inf")
    r = 1.0 / alpha
    return float(
        np.sum(
            _lgamma_vec(y + r)
 - _lgamma_vec(y + 1.0)
 - math.lgamma(r)
            + r * (math.log(r) - np.log(r + m))
            + y * (np.log(m) - np.log(r + m))
        )
    )


def _zero_inflate_loglik(
    y: np.ndarray, log_p0: np.ndarray, log_py: np.ndarray, pi: float
) -> float:
    """Combine a count-model density with a structural-zero component.

    Args:
        y: Counts.
        log_p0: Log P(Y=0) under the count component, per observation.
        log_py: Log P(Y=y) under the count component, per observation.
        pi: Structural-zero probability in (0, 1).

    Returns:
        Zero-inflated log-likelihood, or ``-inf`` on invalid input.
    """
    if not (0.0 < pi < 1.0):
        return float("-inf")
    is_zero = y == 0
    log1m = math.log1p(-pi)
    # log(pi + (1-pi) * p0) computed stably.
    a = math.log(pi)
    b = log1m + log_p0[is_zero]
    mx = np.maximum(a, b)
    zero_term = mx + np.log(np.exp(a - mx) + np.exp(b - mx))
    return float(np.sum(zero_term) + np.sum(log1m + log_py[~is_zero]))


def fit_poisson(y: np.ndarray, exposure: Optional[np.ndarray] = None) -> CountFit:
    """Fit a Poisson model with exposure offset in closed form.

    The MLE of ``mu`` is ``sum(y) / sum(exposure)``; no optimiser is needed.

    Args:
        y: Counts.
        exposure: Exposure per observation.

    Returns:
        A :class:`CountFit`.
    """
    y, e = prepare_counts(y, exposure)
    mu = float(y.sum() / e.sum())
    m = e * mu
    # All-zero data is a legitimate degenerate case: mu = 0 puts probability 1
    # on every observed zero, so the log-likelihood is exactly 0.
    ll = poisson_loglik(y, m) if mu > 0 else 0.0
    exp_zeros = float(np.sum(np.exp(-m))) if mu > 0 else float(len(y))
    return CountFit(
        model="poisson",
        params={"mu": mu},
        loglik=ll,
        n=int(y.size),
        k=1,
        converged=True,
        expected_zeros=exp_zeros,
        observed_zeros=int(np.sum(y == 0)),
    )


def fit_nb2(y: np.ndarray, exposure: Optional[np.ndarray] = None) -> CountFit:
    """Fit an NB2 model with exposure offset by maximum likelihood.

    Args:
        y: Counts.
        exposure: Exposure per observation.

    Returns:
        A :class:`CountFit` with ``mu`` and ``alpha``.
    """
    y, e = prepare_counts(y, exposure)
    mu0 = max(float(y.sum() / e.sum()), 1e-9)
    var, mean = float(np.var(y)), float(np.mean(y))
    a0 = max((var - mean) / max(mean**2, 1e-12), 1e-3)

    def nll(v: np.ndarray) -> float:
        if not (_softplus_inv_ok(v[0]) and _softplus_inv_ok(v[1])):
            return float("inf")
        mu, alpha = math.exp(v[0]), math.exp(v[1])
        ll = nb2_loglik(y, e * mu, alpha)
        return -ll if np.isfinite(ll) else float("inf")

    starts = [
        [math.log(mu0), math.log(a0)],
        [math.log(mu0), math.log(max(a0 * 5, 1e-2))],
        [math.log(mu0), math.log(0.1)],
    ]
    res = multistart_nelder_mead(nll, starts, step=0.5, max_iter=4000)
    mu, alpha = math.exp(res.x[0]), math.exp(res.x[1])
    r = 1.0 / alpha
    m = e * mu
    exp_zeros = float(np.sum(np.exp(r * (math.log(r) - np.log(r + m)))))
    return CountFit(
        model="nb2",
        params={"mu": mu, "alpha": alpha},
        loglik=-res.fun,
        n=int(y.size),
        k=2,
        converged=res.converged,
        expected_zeros=exp_zeros,
        observed_zeros=int(np.sum(y == 0)),
        optimizer=res,
    )


def fit_zip(y: np.ndarray, exposure: Optional[np.ndarray] = None) -> CountFit:
    """Fit a zero-inflated Poisson model with exposure offset.

    Args:
        y: Counts.
        exposure: Exposure per observation.

    Returns:
        A :class:`CountFit` with ``mu`` and ``pi``.
    """
    y, e = prepare_counts(y, exposure)
    mu0 = max(float(y.sum() / e.sum()), 1e-9)
    obs_zero = float(np.mean(y == 0))
    pi0 = min(max(obs_zero - math.exp(-mu0 * float(np.mean(e))), 1e-3), 0.9)

    def nll(v: np.ndarray) -> float:
        if not (_softplus_inv_ok(v[0]) and _softplus_inv_ok(v[1])):
            return float("inf")
        mu, pi = math.exp(v[0]), _expit(v[1])
        m = e * mu
        if np.any(~np.isfinite(m)) or np.any(m <= 0):
            return float("inf")
        log_p0 = -m
        log_py = y * np.log(m) - m - _lgamma_vec(y + 1.0)
        ll = _zero_inflate_loglik(y, log_p0, log_py, pi)
        return -ll if np.isfinite(ll) else float("inf")

    starts = [
        [math.log(mu0), _logit(pi0)],
        [math.log(mu0 * 1.5), _logit(max(pi0, 0.05))],
        [math.log(mu0), _logit(0.3)],
    ]
    res = multistart_nelder_mead(nll, starts, step=0.5, max_iter=4000)
    mu, pi = math.exp(res.x[0]), _expit(res.x[1])
    m = e * mu
    exp_zeros = float(np.sum(pi + (1 - pi) * np.exp(-m)))
    return CountFit(
        model="zip",
        params={"mu": mu, "pi": pi},
        loglik=-res.fun,
        n=int(y.size),
        k=2,
        converged=res.converged,
        expected_zeros=exp_zeros,
        observed_zeros=int(np.sum(y == 0)),
        optimizer=res,
    )


def fit_zinb(y: np.ndarray, exposure: Optional[np.ndarray] = None) -> CountFit:
    """Fit a zero-inflated NB2 model with exposure offset.

    Args:
        y: Counts.
        exposure: Exposure per observation.

    Returns:
        A :class:`CountFit` with ``mu``, ``alpha`` and ``pi``.
    """
    y, e = prepare_counts(y, exposure)
    mu0 = max(float(y.sum() / e.sum()), 1e-9)
    var, mean = float(np.var(y)), float(np.mean(y))
    a0 = max((var - mean) / max(mean**2, 1e-12), 1e-3)

    def nll(v: np.ndarray) -> float:
        if not all(_softplus_inv_ok(x) for x in v):
            return float("inf")
        mu, alpha, pi = math.exp(v[0]), math.exp(v[1]), _expit(v[2])
        if alpha <= 0:
            return float("inf")
        m = e * mu
        if np.any(~np.isfinite(m)) or np.any(m <= 0):
            return float("inf")
        r = 1.0 / alpha
        log_p0 = r * (math.log(r) - np.log(r + m))
        log_py = (
            _lgamma_vec(y + r)
 - _lgamma_vec(y + 1.0)
 - math.lgamma(r)
            + log_p0
            + y * (np.log(m) - np.log(r + m))
        )
        ll = _zero_inflate_loglik(y, log_p0, log_py, pi)
        return -ll if np.isfinite(ll) else float("inf")

    starts = [
        [math.log(mu0), math.log(a0), _logit(0.10)],
        [math.log(mu0), math.log(max(a0, 0.5)), _logit(0.25)],
        [math.log(mu0), math.log(0.1), _logit(0.05)],
        [math.log(mu0 * 1.3), math.log(max(a0 * 2, 0.2)), _logit(0.4)],
    ]
    res = multistart_nelder_mead(nll, starts, step=0.4, max_iter=6000)
    mu, alpha, pi = math.exp(res.x[0]), math.exp(res.x[1]), _expit(res.x[2])
    r = 1.0 / alpha
    m = e * mu
    exp_zeros = float(
        np.sum(pi + (1 - pi) * np.exp(r * (math.log(r) - np.log(r + m))))
    )
    return CountFit(
        model="zinb",
        params={"mu": mu, "alpha": alpha, "pi": pi},
        loglik=-res.fun,
        n=int(y.size),
        k=3,
        converged=res.converged,
        expected_zeros=exp_zeros,
        observed_zeros=int(np.sum(y == 0)),
        optimizer=res,
    )


def boundary_lrt(restricted: CountFit, full: CountFit) -> Dict[str, float]:
    """Likelihood-ratio test where the restriction sits on a parameter boundary.

    For ZINB vs NB2 (or ZIP vs Poisson) the null is ``pi = 0``, which is on the
    boundary of ``[0, 1)``. The asymptotic null distribution of the LR statistic
    is then a 50:50 mixture of a point mass at zero and chi-square(1)
    (Chernoff 1954; Self & Liang 1987), so the correct p-value is half the
    ordinary chi-square(1) tail probability.

    Args:
        restricted: Fit of the nested model (e.g. NB2).
        full: Fit of the enclosing model (e.g. ZINB).

    Returns:
        ``lr_statistic``, ``df``, ``p_value_naive_chi2``, ``p_value_boundary``.

    Raises:
        ValueError: If the full model does not have more parameters.
    """
    df = full.k - restricted.k
    if df <= 0:
        raise ValueError("full model must have more parameters than restricted")
    lr = 2.0 * (full.loglik - restricted.loglik)
    lr = max(lr, 0.0)
    p_naive = _chi2_sf(lr, df)
    return {
        "lr_statistic": float(lr),
        "df": float(df),
        "p_value_naive_chi2": float(p_naive),
        "p_value_boundary": float(0.5 * p_naive),
    }


def _chi2_sf(x: float, df: int) -> float:
    """Upper tail of the chi-square distribution.

    Implemented via the regularised upper incomplete gamma function so that no
    SciPy dependency is needed.

    Args:
        x: Statistic value, >= 0.
        df: Degrees of freedom, >= 1.

    Returns:
        ``P(X > x)``.
    """
    if x <= 0:
        return 1.0
    return _gammaincc(df / 2.0, x / 2.0)


def _gammaincc(a: float, x: float) -> float:
    """Regularised upper incomplete gamma ``Q(a, x)``.

    Uses the series for ``P(a, x)`` when ``x < a + 1`` and Lentz's continued
    fraction for ``Q(a, x)`` otherwise (Numerical Recipes, 3rd ed., section 6.2).

    Args:
        a: Shape, > 0.
        x: Argument, >= 0.

    Returns:
        ``Q(a, x)`` in [0, 1].
    """
    if x < 0 or a <= 0:
        return float("nan")
    if x == 0:
        return 1.0
    gln = math.lgamma(a)
    if x < a + 1.0:
        ap, s, d = a, 1.0 / a, 1.0 / a
        for _ in range(1000):
            ap += 1.0
            d *= x / ap
            s += d
            if abs(d) < abs(s) * 1e-15:
                break
        return 1.0 - s * math.exp(-x + a * math.log(x) - gln)
    tiny = 1e-300
    b, c = x + 1.0 - a, 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            break
    return math.exp(-x + a * math.log(x) - gln) * h


def compare_models(
    y: np.ndarray,
    exposure: Optional[np.ndarray] = None,
    models: Sequence[str] = ("poisson", "nb2", "zip", "zinb"),
) -> Tuple[List[CountFit], Dict[str, Dict[str, float]]]:
    """Fit several count models to the same data and compare them.

    Args:
        y: Counts.
        exposure: Exposure per observation.
        models: Which models to fit.

    Returns:
        ``(fits, tests)`` where ``fits`` is in the order requested and ``tests``
        holds boundary-corrected LR tests for the nested pairs that were fitted.

    Raises:
        ValueError: If an unknown model name is requested.
    """
    fitters = {
        "poisson": fit_poisson,
        "nb2": fit_nb2,
        "zip": fit_zip,
        "zinb": fit_zinb,
    }
    unknown = [m for m in models if m not in fitters]
    if unknown:
        raise ValueError(f"unknown model(s): {unknown}")
    fits = [fitters[m](y, exposure) for m in models]
    by_name = {f.model: f for f in fits}
    tests: Dict[str, Dict[str, float]] = {}
    for restricted, full in (("poisson", "zip"), ("nb2", "zinb")):
        if restricted in by_name and full in by_name:
            tests[f"{full}_vs_{restricted}"] = boundary_lrt(
                by_name[restricted], by_name[full]
            )
    # Poisson vs NB2 is also a boundary test (alpha = 0).
    if "poisson" in by_name and "nb2" in by_name:
        tests["nb2_vs_poisson"] = boundary_lrt(by_name["poisson"], by_name["nb2"])
    return fits, tests


def predicted_count_distribution(
    fit: CountFit, exposure: np.ndarray, max_count: int = 10
) -> np.ndarray:
    """Model-implied expected number of establishments at each count value.

    Args:
        fit: A fitted model.
        exposure: Exposure vector the model was fitted on.
        max_count: Highest count to tabulate; the last cell is the tail.

    Returns:
        Array of length ``max_count + 1``; index ``k`` is the expected number of
        observations with ``y == k``, except the last which is ``y >= max_count``.

    Raises:
        ValueError: If the model name is unrecognised.
    """
    if fit.model not in {"poisson", "nb2", "zip", "zinb"}:
        raise ValueError(f"unrecognised model {fit.model!r}")
    e = np.asarray(exposure, dtype="float64").ravel()
    mu = fit.params["mu"]
    m = e * mu
    pi = fit.params.get("pi", 0.0)
    alpha = fit.params.get("alpha")

    out = np.zeros(max_count + 1, dtype="float64")
    cum = np.zeros_like(m)
    for k in range(max_count):
        if alpha is None:
            logp = k * np.log(m) - m - math.lgamma(k + 1)
        else:
            r = 1.0 / alpha
            logp = (
                math.lgamma(k + r)
 - math.lgamma(k + 1)
 - math.lgamma(r)
                + r * (math.log(r) - np.log(r + m))
                + k * (np.log(m) - np.log(r + m))
            )
        p = np.exp(logp)
        p = (1 - pi) * p + (pi if k == 0 else 0.0)
        out[k] = float(np.sum(p))
        cum += p
    out[max_count] = float(np.sum(np.clip(1.0 - cum, 0.0, None)))
    return out
