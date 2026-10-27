"""Rate detectability: exact Poisson intervals and hours needed to tell two TRIRs apart.

A TRIR is ``200000 * cases / hours``. For a fixed rate, cases in a year are
modelled as Poisson with mean ``rate * hours / 200000``. Everything here is exact
(no normal approximation) and uses only the standard library plus numpy.

Functions
---------
``garwood_interval``  exact (Garwood) confidence interval for a Poisson mean.
``trir_interval``     the same, scaled to a TRIR.
``cases_for_precision`` smallest case count whose interval upper/lower ratio is
    at most a target.
``power_two_rates``   exact power of the conditional binomial test of two rates
    observed over equal hours.
``hours_for_power``   smallest hours per arm reaching a target power.

Model limits (stated, not hidden): the committed size-band table shows the
variance-to-mean ratio of establishment case counts is well above 1, so real
establishments are overdispersed relative to Poisson. Poisson intervals are
therefore a best case: real detectability is worse.
"""

from __future__ import annotations

import math
from typing import Tuple

import numpy as np

HOURS_PER_RATE_UNIT = 200000.0


def _poisson_cdf(k: int, mu: float) -> float:
    """P(X <= k) for X ~ Poisson(mu), by direct summation in log space."""
    if mu <= 0:
        return 1.0
    total = 0.0
    log_mu = math.log(mu)
    for i in range(k + 1):
        total += math.exp(-mu + i * log_mu - math.lgamma(i + 1))
    return min(total, 1.0)


def _bisect(f, lo: float, hi: float, iters: int = 200) -> float:
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if f(mid) > 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def garwood_interval(k: int, conf: float = 0.95) -> Tuple[float, float]:
    """Exact two-sided confidence interval for a Poisson mean given count ``k``.

    Lower bound mu_L solves P(X >= k | mu_L) = alpha/2 (0 when k = 0); upper
    bound mu_U solves P(X <= k | mu_U) = alpha/2.
    """
    if k < 0:
        raise ValueError("k must be non-negative")
    a = (1.0 - conf) / 2.0
    upper_hi = k + 10.0 * math.sqrt(k + 1.0) + 20.0
    upper = _bisect(lambda mu: a - _poisson_cdf(k, mu), 0.0, upper_hi)
    if k == 0:
        return 0.0, upper
    lower = _bisect(lambda mu: (1.0 - _poisson_cdf(k - 1, mu)) - a, 0.0, float(k))
    return lower, upper


def trir_interval(cases: int, hours: float, conf: float = 0.95) -> Tuple[float, float]:
    """Exact confidence interval for a TRIR from ``cases`` over ``hours``."""
    if hours <= 0:
        raise ValueError("hours must be positive")
    lo, hi = garwood_interval(cases, conf)
    return HOURS_PER_RATE_UNIT * lo / hours, HOURS_PER_RATE_UNIT * hi / hours


def cases_for_precision(max_ratio: float, conf: float = 0.95) -> int:
    """Smallest count k >= 1 with Garwood upper/lower <= ``max_ratio``."""
    k = 1
    while True:
        lo, hi = garwood_interval(k, conf)
        if hi / lo <= max_ratio:
            return k
        k += 1


def _log_binom_pmf(n: int, p: float) -> np.ndarray:
    """log pmf of Binomial(n, p) over 0..n via a stable recurrence."""
    k = np.arange(1, n + 1, dtype="float64")
    steps = np.log((n - k + 1.0) / k) + math.log(p) - math.log1p(-p)
    log_pmf = np.concatenate(([n * math.log1p(-p)], n * math.log1p(-p) + np.cumsum(steps)))
    return log_pmf


def _critical_value(n: int, alpha: float) -> int:
    """Largest c with 2 * P(Bin(n, 1/2) <= c) <= alpha; -1 if none."""
    if n == 0:
        return -1
    pmf = np.exp(_log_binom_pmf(n, 0.5))
    cdf = np.cumsum(pmf)
    ok = np.nonzero(2.0 * cdf <= alpha)[0]
    return int(ok[-1]) if len(ok) else -1


def power_two_rates(rate1: float, rate2: float, hours: float, alpha: float = 0.05) -> float:
    """Exact power of the two-sided conditional test of equal rates.

    Counts X1, X2 are independent Poisson over equal ``hours``. Conditional on
    n = X1 + X2, X1 is Binomial(n, 1/2) under the null; the test rejects when
    the exact two-sided binomial p-value is <= ``alpha``. Power sums over n.
    """
    if rate1 <= 0 or rate2 <= 0 or hours <= 0:
        raise ValueError("rates and hours must be positive")
    m1, m2 = rate1 * hours / HOURS_PER_RATE_UNIT, rate2 * hours / HOURS_PER_RATE_UNIT
    mt = m1 + m2
    p = m2 / mt
    sd = math.sqrt(mt)
    n_lo = max(1, int(mt - 10 * sd - 5))
    n_hi = int(mt + 10 * sd + 5)
    power = 0.0
    for n in range(n_lo, n_hi + 1):
        c = _critical_value(n, alpha)
        if c < 0:
            continue
        pn = math.exp(-mt + n * math.log(mt) - math.lgamma(n + 1))
        pmf = np.exp(_log_binom_pmf(n, p))
        reject = pmf[: c + 1].sum() + pmf[n - c :].sum()
        power += pn * reject
    return float(min(power, 1.0))


def hours_for_power(rate1: float, rate2: float, target: float = 0.8, alpha: float = 0.05) -> float:
    """Smallest hours per arm with exact power >= ``target``, to 1% resolution.

    Exact power is not monotone in hours (counts are discrete), so the search
    steps up geometrically by 1% from a lower bound and returns the first
    hours value that reaches the target.
    """
    # Normal-approximation hours, halved, only to start the search below the
    # answer; the returned value always comes from the exact calculation.
    z = 1.959964 + 0.841621
    approx = z * z * (rate1 + rate2) / (rate1 - rate2) ** 2 * HOURS_PER_RATE_UNIT
    hours = max(1.0, 0.5 * approx)
    while power_two_rates(rate1, rate2, hours, alpha) < target:
        hours *= 1.01
    return hours


#: Rate ratios for which hours-needed columns are computed.
RATIOS = (1.25, 1.5, 2.0)
#: Target upper/lower ratio of the interval used for "precise enough".
PRECISION_RATIO = 2.0


def build_table(size_bands):
    """Detectability per establishment size band from ``size_band_effects``.

    Args:
        size_bands: Frame with ``size_band``, ``n``, ``mean_recordables`` and
            ``aggregate_trir`` (as written by the pipeline).

    Returns:
        One row per band. Hours per filing are implied: mean cases times 200000
        over the aggregate TRIR. A "site-year" is one filing of mean size.
    """
    import pandas as pd

    k_prec = cases_for_precision(PRECISION_RATIO)
    zero_upper = garwood_interval(0)[1]
    rows = []
    for rec in size_bands.itertuples(index=False):
        rate = float(rec.aggregate_trir)
        h = float(rec.mean_recordables) * HOURS_PER_RATE_UNIT / rate
        hours_prec = k_prec * HOURS_PER_RATE_UNIT / rate
        row = {
            "size_band": rec.size_band,
            "n_filings": int(rec.n),
            "aggregate_trir": rate,
            "mean_hours_per_filing": h,
            "mean_cases_per_filing": float(rec.mean_recordables),
            "trir_upper_bound_if_zero_cases": HOURS_PER_RATE_UNIT * zero_upper / h,
            "cases_for_upper_over_lower_le_2": k_prec,
            "hours_for_upper_over_lower_le_2": hours_prec,
            "site_years_for_upper_over_lower_le_2": hours_prec / h,
        }
        for ratio in RATIOS:
            need = hours_for_power(rate, rate * ratio)
            tag = f"{ratio:g}".replace(".", "_")
            row[f"power_one_site_year_each_ratio_{tag}"] = power_two_rates(rate, rate * ratio, h)
            row[f"site_years_per_arm_80pct_ratio_{tag}"] = need / h
        rows.append(row)
    return pd.DataFrame(rows)
