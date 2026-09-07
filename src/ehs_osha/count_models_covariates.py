"""Count models with covariates: log-hours offset, size-band and NAICS fixed
effects, fitted by maximum likelihood with NumPy only.

This module answers the reviewer's objection to the intercept-only comparison
in :mod:`ehs_osha.countmodels`: an intercept-only NB2 or ZINB can "win" against
Poisson simply because establishments differ in size and sub-industry, which
is heterogeneity in the mean, not overdispersion of the conditional count.
The question that matters is whether the variance still exceeds the mean
*after* conditioning on the observable structure.

Specification
-------------
Mean:  ``log E[y_i | x_i] = log(hours_i / 200000) + x_i' beta``

``x_i`` holds an intercept, size-band dummies (reference: the smallest band)
and fixed effects for the sub-industry. Within one NAICS 3-digit industry the
3-digit code is constant, so the within-industry fixed effects are NAICS
4-digit dummies (reference: the largest 4-digit group). The pooled fit across
all selected industries uses NAICS 3-digit dummies. Dummy-coded fixed effects
are used, not a random-intercept approximation: the number of levels is small
enough (tens, not thousands) for dense NumPy linear algebra.

Zero inflation: ``pi`` is a single constant per fit (no covariates in the
inflation equation). This is deliberate. With covariates in both equations the
ZIP/ZINB inflation parameters are identified only through the functional form,
and on data with a large share of small establishments that identification is
weak. A constant ``pi`` is identified from the excess of zeros over the
covariate-adjusted count component and is directly comparable to the
intercept-only ``pi`` reported elsewhere.

Estimation
----------
* Poisson: Newton-Raphson (IRLS) on ``beta``.
* NB2: alternating IRLS for ``beta`` given ``alpha`` and golden-section search
  for ``log alpha`` given ``beta``.
* ZIP / ZINB: EM with the latent structural-zero indicator; the M-step is a
  weighted Poisson / NB2 fit. The reported log-likelihood is the observed-data
  likelihood, not the EM objective.

The boundary-corrected LR tests of :func:`ehs_osha.countmodels.boundary_lrt`
are reused unchanged.
"""

from __future__ import annotations

import math
import warnings
from typing import Dict, List, Optional, Sequence, Tuple

from pathlib import Path

import numpy as np
import pandas as pd

from .countmodels import CountFit, _lgamma_vec, boundary_lrt
from .optimize import golden_section

MODELS = ("poisson", "nb2", "zip", "zinb")
# macOS Accelerate emits spurious matmul RuntimeWarnings that np.errstate does
# not silence; the results are checked for finiteness explicitly.
warnings.filterwarnings("ignore", message=".*encountered in matmul")
_MAX_ETA = 30.0


# ---------------------------------------------------------------- design ----


def design_matrix(
    size_band: Sequence[object], fe: Optional[Sequence[object]] = None
) -> Tuple[np.ndarray, List[str]]:
    """Build an intercept + dummy design matrix.

    Args:
        size_band: Size-band label per row; the first label in sorted order
            (the smallest band, given the ``1-10`` style labels) is the
            reference.
        fe: Optional fixed-effect label per row; the modal level is the
            reference.

    Returns:
        ``(X, names)`` with ``X`` of shape ``(n, p)``.
    """
    sb = pd.Series(list(size_band)).astype(str)
    cols = [np.ones(len(sb))]
    names = ["intercept"]
    levels = sorted(sb.unique(), key=_band_sort_key)
    for lv in levels[1:]:
        cols.append((sb == lv).to_numpy(dtype="float64"))
        names.append(f"size_band[{lv}]")
    if fe is not None:
        f = pd.Series(list(fe)).astype(str)
        counts = f.value_counts()
        for lv in counts.index[1:]:
            cols.append((f == lv).to_numpy(dtype="float64"))
            names.append(f"fe[{lv}]")
    X = np.column_stack(cols)
    # Drop columns that are all zero or duplicate the intercept (empty levels).
    keep = [i for i in range(X.shape[1]) if i == 0 or 0 < X[:, i].sum() < len(sb)]
    return X[:, keep], [names[i] for i in keep]


def _band_sort_key(label: str) -> Tuple[float, str]:
    head = label.split("-")[0].replace("+", "").replace(",", "").strip()
    try:
        return (float(head), label)
    except ValueError:
        return (float("inf"), label)


# ------------------------------------------------------------ likelihoods ----


def _mean(X: np.ndarray, beta: np.ndarray, log_e: np.ndarray) -> np.ndarray:
    eta = np.clip(X @ beta + log_e, -_MAX_ETA, _MAX_ETA)
    return np.exp(eta)


def _pois_logp(y: np.ndarray, m: np.ndarray) -> np.ndarray:
    return y * np.log(m) - m - _lgamma_vec(y + 1.0)


def _nb_logp(y: np.ndarray, m: np.ndarray, alpha: float) -> np.ndarray:
    r = 1.0 / alpha
    return (
        _lgamma_vec(y + r)
        - _lgamma_vec(y + 1.0)
        - math.lgamma(r)
        + r * (math.log(r) - np.log(r + m))
        + y * (np.log(m) - np.log(r + m))
    )


def _zi_loglik(y: np.ndarray, logp: np.ndarray, log_p0: np.ndarray, pi: float) -> float:
    if pi <= 0.0:
        return float(np.sum(logp))
    is0 = y == 0
    a = math.log(pi)
    b = math.log1p(-pi) + log_p0[is0]
    mx = np.maximum(a, b)
    zero_term = mx + np.log(np.exp(a - mx) + np.exp(b - mx))
    return float(np.sum(zero_term) + np.sum(math.log1p(-pi) + logp[~is0]))


# -------------------------------------------------------------- M-steps ----


def _poisson_irls(
    y: np.ndarray,
    X: np.ndarray,
    log_e: np.ndarray,
    w: Optional[np.ndarray] = None,
    beta0: Optional[np.ndarray] = None,
    max_iter: int = 50,
    tol: float = 1e-8,
) -> Tuple[np.ndarray, bool]:
    """Weighted Poisson regression by Newton-Raphson with a step halving."""
    n, p = X.shape
    w = np.ones(n) if w is None else w
    beta = np.zeros(p) if beta0 is None else beta0.copy()
    if beta0 is None:
        beta[0] = math.log(max(float(np.sum(w * y) / np.sum(w * np.exp(log_e))), 1e-9))
    m = _mean(X, beta, log_e)
    ll = float(np.sum(w * _pois_logp(y, m)))
    converged = False
    for _ in range(max_iter):
        grad = X.T @ (w * (y - m))
        H = (X * (w * m)[:, None]).T @ X + 1e-10 * np.eye(p)
        step = np.linalg.solve(H, grad)
        t = 1.0
        while t > 1e-4:
            cand = beta + t * step
            mc = _mean(X, cand, log_e)
            llc = float(np.sum(w * _pois_logp(y, mc)))
            if llc >= ll - 1e-12:
                break
            t *= 0.5
        beta, m = cand, mc
        if abs(llc - ll) < tol * (1 + abs(ll)):
            converged = True
            ll = llc
            break
        ll = llc
    return beta, converged


def _nb2_fit(
    y: np.ndarray,
    X: np.ndarray,
    log_e: np.ndarray,
    w: Optional[np.ndarray] = None,
    beta0: Optional[np.ndarray] = None,
    alpha0: float = 0.5,
    outer: int = 25,
) -> Tuple[np.ndarray, float, bool]:
    """Weighted NB2 regression by alternating IRLS (beta) and 1-d search (alpha)."""
    n, p = X.shape
    w = np.ones(n) if w is None else w
    beta, _ = _poisson_irls(y, X, log_e, w, beta0)
    alpha = alpha0
    prev = -float("inf")
    converged = False
    for _ in range(outer):
        # beta step: Newton on the NB2 log-likelihood at fixed alpha.
        m = _mean(X, beta, log_e)
        ll_b = float(np.sum(w * _nb_logp(y, m, alpha)))
        for _inner in range(10):
            g = w * (y - m) / (1.0 + alpha * m)
            wt = w * m / (1.0 + alpha * m)
            H = (X * wt[:, None]).T @ X + 1e-10 * np.eye(p)
            step = np.linalg.solve(H, X.T @ g)
            t = 1.0
            while t > 1e-4:
                cand = beta + t * step
                mc = _mean(X, cand, log_e)
                llc = float(np.sum(w * _nb_logp(y, mc, alpha)))
                if llc >= ll_b - 1e-12:
                    break
                t *= 0.5
            beta, m = cand, mc
            done = abs(llc - ll_b) < 1e-9 * (1 + abs(ll_b))
            ll_b = llc
            if done:
                break

        def prof(la: float) -> float:
            return -float(np.sum(w * _nb_logp(y, m, math.exp(la))))

        la = golden_section(prof, math.log(1e-4), math.log(50.0), tol=1e-6)
        alpha = math.exp(la[0])
        ll = float(np.sum(w * _nb_logp(y, m, alpha)))
        if abs(ll - prev) < 1e-8 * (1 + abs(ll)):
            converged = True
            break
        prev = ll
    return beta, float(alpha), converged


# ----------------------------------------------------------------- fits ----


def fit_with_covariates(
    y: np.ndarray,
    exposure: np.ndarray,
    X: np.ndarray,
    model: str,
    names: Optional[Sequence[str]] = None,
    em_iter: int = 200,
) -> CountFit:
    """Fit one of Poisson / NB2 / ZIP / ZINB with a covariate mean.

    Args:
        y: Counts.
        exposure: Exposure in 200,000-hour units, strictly positive.
        X: Design matrix with an intercept column first.
        model: One of :data:`MODELS`.
        names: Column names for ``X``; used as parameter keys.
        em_iter: Maximum EM iterations for the zero-inflated models.

    Returns:
        A :class:`ehs_osha.countmodels.CountFit`. ``params`` holds the
        regression coefficients keyed by ``names`` plus ``alpha`` / ``pi``
        where applicable, and ``mu`` is the exposure-weighted mean rate
        implied by the fit so the field stays comparable to the
        intercept-only output.

    Raises:
        ValueError: On an unknown model or inconsistent shapes.
    """
    if model not in MODELS:
        raise ValueError(f"unknown model {model!r}")
    with np.errstate(all="ignore"):
        return _fit_with_covariates(y, exposure, X, model, names, em_iter)


def _fit_with_covariates(
    y: np.ndarray,
    exposure: np.ndarray,
    X: np.ndarray,
    model: str,
    names: Optional[Sequence[str]],
    em_iter: int,
) -> CountFit:
    y = np.asarray(y, dtype="float64").ravel()
    e = np.asarray(exposure, dtype="float64").ravel()
    X = np.asarray(X, dtype="float64")
    if X.shape[0] != y.size or e.size != y.size:
        raise ValueError("y, exposure and X must have the same number of rows")
    if np.any(e <= 0) or np.any(y < 0):
        raise ValueError("exposure must be positive and counts non-negative")
    names = list(names) if names is not None else [f"b{i}" for i in range(X.shape[1])]
    log_e = np.log(e)
    n, p = X.shape
    inflated = model in ("zip", "zinb")
    nb = model in ("nb2", "zinb")

    pi = 0.0
    alpha = float("nan")
    w = np.ones(n)
    beta = None
    converged = True
    ll_prev = -float("inf")
    ll = -float("inf")
    for it in range(em_iter if inflated else 1):
        if nb:
            beta, alpha, conv = _nb2_fit(y, X, log_e, w, beta, alpha if it else 0.5)
        else:
            beta, conv = _poisson_irls(y, X, log_e, w, beta)
        m = _mean(X, beta, log_e)
        logp = _nb_logp(y, m, alpha) if nb else _pois_logp(y, m)
        log_p0 = (
            (1.0 / alpha) * (math.log(1.0 / alpha) - np.log(1.0 / alpha + m))
            if nb
            else -m
        )
        if not inflated:
            ll = float(np.sum(logp))
            converged = conv
            break
        # E-step.
        is0 = y == 0
        z = np.zeros(n)
        if pi <= 0.0:
            pi = 0.5 * float(np.mean(is0))  # first-pass start
        num = math.log(pi)
        den = np.logaddexp(num, math.log1p(-pi) + log_p0[is0])
        z[is0] = np.exp(num - den)
        pi_new = float(np.clip(np.mean(z), 1e-8, 1 - 1e-8))
        ll = _zi_loglik(y, logp, log_p0, pi_new)
        w = 1.0 - z
        converged = abs(ll - ll_prev) < 1e-8 * (1 + abs(ll))
        pi = pi_new
        if converged:
            break
        ll_prev = ll

    m = _mean(X, beta, log_e)
    if nb:
        r = 1.0 / alpha
        p0 = np.exp(r * (math.log(r) - np.log(r + m)))
    else:
        p0 = np.exp(-m)
    exp_zeros = float(np.sum(pi + (1 - pi) * p0))
    params: Dict[str, float] = {nm: float(b) for nm, b in zip(names, beta)}
    params["mu"] = float(np.sum(m) / np.sum(e))
    k = p
    if nb:
        params["alpha"] = float(alpha)
        k += 1
    if inflated:
        params["pi"] = float(pi)
        k += 1
    return CountFit(
        model=model,
        params=params,
        loglik=float(ll),
        n=int(n),
        k=int(k),
        converged=bool(converged),
        expected_zeros=exp_zeros,
        observed_zeros=int(np.sum(y == 0)),
    )


def compare_with_covariates(
    y: np.ndarray, exposure: np.ndarray, X: np.ndarray, names: Sequence[str]
) -> Tuple[List[CountFit], Dict[str, Dict[str, float]]]:
    """Fit all four models with the same covariates and run boundary LR tests."""
    fits = [fit_with_covariates(y, exposure, X, m, names) for m in MODELS]
    by = {f.model: f for f in fits}
    tests = {
        "nb2_vs_poisson": boundary_lrt(by["poisson"], by["nb2"]),
        "zip_vs_poisson": boundary_lrt(by["poisson"], by["zip"]),
        "zinb_vs_nb2": boundary_lrt(by["nb2"], by["zinb"]),
    }
    return fits, tests


def expected_count_distribution(
    fit: CountFit, exposure: np.ndarray, X: np.ndarray, names: Sequence[str], max_count: int = 10
) -> np.ndarray:
    """Model-implied expected number of observations at each count value."""
    beta = np.array([fit.params[nm] for nm in names])
    m = _mean(X, beta, np.log(np.asarray(exposure, dtype="float64")))
    pi = fit.params.get("pi", 0.0)
    alpha = fit.params.get("alpha")
    out = np.zeros(max_count + 1)
    cum = np.zeros_like(m)
    for k in range(max_count):
        yk = np.full_like(m, float(k))
        logp = _nb_logp(yk, m, alpha) if alpha is not None else _pois_logp(yk, m)
        pk = (1 - pi) * np.exp(logp) + (pi if k == 0 else 0.0)
        out[k] = float(np.sum(pk))
        cum += pk
    out[max_count] = float(np.sum(np.clip(1.0 - cum, 0.0, None)))
    return out


# ------------------------------------------------------------- summaries ----


def summarize_table(table: pd.DataFrame, tables_dir: "Path") -> pd.DataFrame:
    """Write ``count_model_covariates_summary.csv`` from the per-fit table.

    Best-by-AIC is reported twice: over all four fits (``is_best_by_aic``) and
    over converged fits only (``is_best_by_aic_converged``). An unconverged
    ZINB fit is one whose EM stalled with ``pi`` at its lower bound; its AIC is
    within a few units of NB2 and its boundary p-value is not interpretable, so
    ``p_boundary_zinb_vs_nb2_converged_only`` is NaN for those rows and the
    headline ZINB counts use converged fits only. The table CSV is rewritten
    with the two added columns.
    """
    table = table.copy()
    best_conv = (
        table[table["converged"].astype(bool)]
        .sort_values("aic")
        .groupby("naics3", sort=False)
        .head(1)[["naics3", "model"]]
    )
    best_key = set(zip(best_conv["naics3"].astype(str), best_conv["model"]))
    table["is_best_by_aic_converged"] = [
        (str(a), m) in best_key for a, m in zip(table["naics3"], table["model"])
    ]
    zinb_conv = table[table["model"] == "zinb"].set_index("naics3")["converged"].astype(bool)
    conv_by_ind = table["naics3"].map(zinb_conv).fillna(False).astype(bool)
    table["p_boundary_zinb_vs_nb2_converged_only"] = np.where(
        conv_by_ind, table["p_boundary_zinb_vs_nb2"], np.nan
    )
    table.to_csv(Path(tables_dir) / "count_model_covariates.csv", index=False)

    wins = table[table["is_best_by_aic"]].groupby("model").size()
    wins_conv = table[table["is_best_by_aic_converged"]].groupby("model").size()
    n_ind = table["naics3"].nunique()
    nb2 = table[table["model"] == "nb2"]
    zinb = table[table["model"] == "zinb"]
    n_unconv = int((~zinb["converged"].astype(bool)).sum())
    summary = pd.DataFrame(
        [
            {"statistic": "n_industries_fitted", "value": n_ind},
            {"statistic": "n_industries_nb2_beats_poisson_p_boundary_lt_0.001",
             "value": int((nb2["p_boundary_nb2_vs_poisson"] < 0.001).sum())},
            {"statistic": "min_delta_aic_nb2_minus_poisson", "value": float(nb2["delta_aic_vs_poisson"].min())},
            {"statistic": "max_delta_aic_nb2_minus_poisson", "value": float(nb2["delta_aic_vs_poisson"].max())},
            {"statistic": "median_alpha_nb2", "value": float(nb2["dispersion_alpha"].median())},
            {"statistic": "min_alpha_nb2", "value": float(nb2["dispersion_alpha"].min())},
            {"statistic": "n_zinb_fits_unconverged_pi_at_boundary", "value": n_unconv},
            {"statistic": "n_industries_zinb_beats_nb2_p_boundary_lt_0.01",
             "value": int((zinb["p_boundary_zinb_vs_nb2"] < 0.01).sum())},
            {"statistic": "n_industries_zinb_beats_nb2_p_boundary_lt_0.01_converged_only",
             "value": int((zinb["p_boundary_zinb_vs_nb2_converged_only"] < 0.01).sum())},
        ]
        + [{"statistic": f"n_industries_best_by_aic_{m}", "value": int(wins.get(m, 0))} for m in MODELS]
        + [{"statistic": f"n_industries_best_by_aic_converged_only_{m}", "value": int(wins_conv.get(m, 0))}
           for m in MODELS]
    )
    summary.to_csv(Path(tables_dir) / "count_model_covariates_summary.csv", index=False)
    return table


def group_coverage(
    data_dir: "Path",
    out_dir: "Path",
    *,
    year: int = 2024,
    top_k: int = 30,
    min_group_n: int = 500,
) -> pd.DataFrame:
    """Write ``count_model_covariates_coverage.csv``: how many NAICS-3 groups
    exist in the screened ``year`` panel, how many clear ``min_group_n``, how
    many are fitted (``top_k``), and the share of establishments and hours the
    fitted groups cover. The fitted set is not a random sample of industries;
    this table says what it leaves out.
    """
    from .load import load_ita_300a
    from .peers import add_peer_keys
    from .quality import apply_screen

    df, _ = load_ita_300a(Path(data_dir), years=[year])
    keyed = add_peer_keys(apply_screen(df))
    base = keyed[(~keyed["implausible"]) & (keyed["year_filing_for"] == year)]
    base = base[base["total_hours_worked"] > 0]
    counts = base["naics3"].value_counts()
    eligible = counts[counts >= min_group_n]
    selected = set(str(c) for c in eligible.index[:top_k])
    in_sel = base["naics3"].astype(str).isin(selected)
    rows = [
        {"statistic": "year", "value": year},
        {"statistic": "n_establishments_screened", "value": int(len(base))},
        {"statistic": "n_naics3_groups_total", "value": int(len(counts))},
        {"statistic": "n_naics3_groups_at_least_min_group_n", "value": int(len(eligible))},
        {"statistic": "n_naics3_groups_fitted", "value": int(len(selected))},
        {"statistic": "n_naics3_groups_dropped_below_min_group_n", "value": int(len(counts) - len(eligible))},
        {"statistic": "n_naics3_groups_dropped_beyond_top_k", "value": int(len(eligible) - len(selected))},
        {"statistic": "share_establishments_in_fitted_groups", "value": float(in_sel.mean())},
        {"statistic": "share_hours_in_fitted_groups",
         "value": float(base.loc[in_sel, "total_hours_worked"].sum() / base["total_hours_worked"].sum())},
        {"statistic": "share_recordable_cases_in_fitted_groups",
         "value": float(base.loc[in_sel, "recordable_cases"].sum() / base["recordable_cases"].sum())},
        {"statistic": "smallest_fitted_group_n", "value": int(eligible.iloc[:top_k].min())},
    ]
    out = pd.DataFrame(rows)
    tables = Path(out_dir) / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    out.to_csv(tables / "count_model_covariates_coverage.csv", index=False)
    return out


# --------------------------------------------------------------- runner ----


def run_real_data(
    data_dir: "Path",
    out_dir: "Path",
    *,
    year: int = 2024,
    top_k: int = 30,
    min_group_n: int = 500,
    max_n: int = 20_000,
    seed: int = 20240901,
    verbose: bool = True,
) -> pd.DataFrame:
    """Fit the covariate-adjusted models on the real OSHA ITA data and write
    ``count_model_covariates.csv``, ``count_model_covariates_summary.csv``,
    ``count_model_covariates_fit_detail.csv`` and ``fig04_count_model_fit.svg``.

    Industry selection mirrors :func:`ehs_osha.pipeline.stage_count_models`:
    the ``top_k`` largest NAICS 3-digit groups with at least ``min_group_n``
    screened establishments in ``year``, chosen on size alone. Groups larger
    than ``max_n`` are randomly subsampled with a fixed seed for runtime.

    Args:
        data_dir: Raw download directory.
        out_dir: Output root holding ``tables/`` and ``figures/``.

    Returns:
        The per-industry, per-model comparison table.
    """
    from pathlib import Path

    from . import svgplot
    from .load import load_ita_300a
    from .peers import add_peer_keys
    from .quality import apply_screen

    df, _ = load_ita_300a(Path(data_dir), years=[year])
    screened = apply_screen(df)
    keyed = add_peer_keys(screened)
    base = keyed[(~keyed["implausible"]) & (keyed["year_filing_for"] == year)]
    base = base[base["total_hours_worked"] > 0]
    counts = base["naics3"].value_counts()
    counts = counts[counts >= min_group_n]
    selected = [str(c) for c in counts.index[:top_k]]
    rng = np.random.default_rng(seed)
    rows: List[dict] = []
    detail_rows: List[dict] = []
    for naics in selected:
        sub = base[base["naics3"] == naics]
        if len(sub) > max_n:
            sub = sub.iloc[np.sort(rng.choice(len(sub), size=max_n, replace=False))]
        y = sub["recordable_cases"].to_numpy(dtype="float64")
        e = sub["total_hours_worked"].to_numpy(dtype="float64") / 200_000.0
        X, names = design_matrix(sub["size_band"].astype(str), sub["naics4"].astype(str))
        if verbose:
            print(f"  NAICS {naics}: n={len(y)}, p={X.shape[1]}")
        fits, tests = compare_with_covariates(y, e, X, names)
        best = min(fits, key=lambda f: f.aic)
        aic_pois = next(f for f in fits if f.model == "poisson").aic
        aic_nb2 = next(f for f in fits if f.model == "nb2").aic
        for f in fits:
            rows.append(
                {
                    "naics3": naics,
                    "year": year,
                    "model": f.model,
                    "n": f.n,
                    "n_params": f.k,
                    "loglik": f.loglik,
                    "aic": f.aic,
                    "bic": f.bic,
                    "delta_aic_vs_poisson": f.aic - aic_pois,
                    "delta_aic_vs_nb2": f.aic - aic_nb2,
                    "is_best_by_aic": f.model == best.model,
                    "converged": f.converged,
                    "dispersion_alpha": f.params.get("alpha", float("nan")),
                    "zero_inflation_pi": f.params.get("pi", float("nan")),
                    "observed_zeros": f.observed_zeros,
                    "expected_zeros": f.expected_zeros,
                    "p_boundary_nb2_vs_poisson": tests["nb2_vs_poisson"]["p_value_boundary"],
                    "p_boundary_zinb_vs_nb2": tests["zinb_vs_nb2"]["p_value_boundary"],
                    "lr_zinb_vs_nb2": tests["zinb_vs_nb2"]["lr_statistic"],
                    "coef_size_band": ";".join(
                        f"{k}={v:.4f}" for k, v in f.params.items() if k.startswith("size_band")
                    ),
                }
            )
            pred = expected_count_distribution(f, e, X, names)
            obs = np.bincount(y.astype(int), minlength=11)[:11].astype("float64")
            obs[10] = float(np.sum(y >= 10))
            for k in range(11):
                detail_rows.append(
                    {"naics3": naics, "model": f.model, "count": k if k < 10 else "10+",
                     "observed": float(obs[k]), "expected": float(pred[k])}
                )
    table = pd.DataFrame(rows)
    tables = Path(out_dir) / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    table.to_csv(tables / "count_model_covariates.csv", index=False)
    pd.DataFrame(detail_rows).to_csv(tables / "count_model_covariates_fit_detail.csv", index=False)

    table = summarize_table(table, tables)

    # Figure 4: observed vs fitted for the largest industry, covariate-adjusted.
    if len(table):
        primary = str(table.sort_values("n", ascending=False)["naics3"].iloc[0])
        det = pd.DataFrame(detail_rows)
        det = det[det["naics3"] == primary]
        labels = [str(v) for v in det[det["model"] == "poisson"]["count"]]
        obs_v = list(det[det["model"] == "poisson"]["observed"].astype(float))
        series = {"observed": obs_v}
        for m in ("poisson", "nb2", "zinb"):
            series[m] = list(det[det["model"] == m]["expected"].astype(float))
        ax = svgplot.Axes(ylim=(0.0, max(obs_v) * 1.2))
        f = svgplot.Figure(
            f"Recordable-case counts, NAICS {primary}, {year}: observed vs fitted "
            "(size band + NAICS-4 fixed effects, log-hours offset)",
            "Recordable cases in the reporting year",
            "Number of establishments",
            ax,
            f"OSHA ITA Form 300A, reporting year {year}, screened panel, NAICS {primary} only; "
            f"n={int(table[table['naics3'] == primary]['n'].iloc[0]):,} establishments in the fit",
        )
        f.bars(labels, series)
        figs = Path(out_dir) / "figures"
        figs.mkdir(parents=True, exist_ok=True)
        f.save(figs / "fig04_count_model_fit.svg")
    return table


if __name__ == "__main__":  # pragma: no cover
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    args = sys.argv[1:]
    if "--summarize-only" in args:
        tables = root / "outputs" / "tables"
        summarize_table(pd.read_csv(tables / "count_model_covariates.csv"), tables)
    elif "--coverage-only" in args:
        print(group_coverage(root / "data" / "raw", root / "outputs").to_string())
    else:
        kw = {}
        if args:
            kw["top_k"] = int(args[0])
        run_real_data(root / "data" / "raw", root / "outputs", **kw)
