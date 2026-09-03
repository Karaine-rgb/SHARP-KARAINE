"""Odds conversion and de-vigging.

Pinnacle's Arcadia API returns American odds. Everything downstream
(displacement thresholds, charts) works in decimal odds and fair
(vig-free) probabilities, so this module is the single place that
conversion happens.
"""
from __future__ import annotations


def american_to_decimal(american: float) -> float:
    """Convert American odds to decimal odds."""
    if american > 0:
        return (american / 100.0) + 1.0
    if american < 0:
        return (100.0 / -american) + 1.0
    raise ValueError("American odds cannot be 0")


def implied_prob(decimal_odds: float) -> float:
    if decimal_odds <= 1.0:
        raise ValueError("Decimal odds must be > 1.0")
    return 1.0 / decimal_odds


def power_devig(implied_probs: list[float], tol: float = 1e-10, max_iter: int = 200) -> list[float]:
    """Power method de-vig.

    Models each raw implied probability as r_i = p_i ** (1/k) for a single
    market-wide exponent k >= 1, where p_i is the true (fair) probability.
    Equivalently p_i = r_i ** k. Solve for k via bisection such that
    sum(r_i ** k) == 1, then return [r_i ** k for r_i in implied_probs].

    This is the standard "power" de-vig method, distinct from Shin's method
    (which instead models a fraction of informed/insider money). Flagging
    the exact formula here since "power devig" alone is ambiguous - if your
    prior build used a different variant, the fair probabilities here may
    not exactly match and the displacement thresholds should be re-checked.
    """
    if not implied_probs:
        return []
    if any(p <= 0 or p >= 1 for p in implied_probs):
        raise ValueError("Implied probabilities must be in (0, 1)")

    total = sum(implied_probs)
    if abs(total - 1.0) < tol:
        return list(implied_probs)

    # sum(r_i ** k) is strictly decreasing in k for k > 0 (since 0 < r_i < 1).
    # total > 1 (overround) => need k > 1 to shrink the sum down to 1.
    # total < 1 (rare, e.g. mid-tranche crossed prices) => need k < 1.
    lo, hi = (1.0, 50.0) if total > 1.0 else (0.02, 1.0)

    def f(k: float) -> float:
        return sum(p**k for p in implied_probs) - 1.0

    f_lo, f_hi = f(lo), f(hi)
    # Expand the bracket if needed rather than assuming it always holds.
    while f_lo * f_hi > 0 and hi < 1000:
        hi *= 2
        f_hi = f(hi)

    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        f_mid = f(mid)
        if abs(f_mid) < tol:
            lo = hi = mid
            break
        if (f_lo > 0) == (f_mid > 0):
            lo, f_lo = mid, f_mid
        else:
            hi, f_hi = mid, f_mid

    k = (lo + hi) / 2.0
    return [p**k for p in implied_probs]


def fair_probs_from_decimal_odds(decimal_odds: list[float]) -> list[float]:
    raw = [implied_prob(o) for o in decimal_odds]
    return power_devig(raw)
