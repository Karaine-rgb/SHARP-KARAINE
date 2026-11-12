"""Poisson goal model fitted to the fair Asian-handicap and fair over probabilities.

Model: home goals ~ Poisson(lh), away goals ~ Poisson(la), independent.
Targets are the de-vigged two-way probabilities of the main AH line (home side)
and the main total line (over side).

Pushes and quarter lines. A de-vigged two-way probability p = 1/(fair decimal
odds) satisfies  stake*odds*P(win) + P(refund) = 1  for a bet that can be
refunded, so  p = P(win) / (1 - P(refund)),  with the stake-weighted win and
refund masses. A quarter line (x.25, x.75) is half a stake on each neighbouring
half/whole line, so its masses are the 50/50 mix of the two components.

Because the over probability depends only on the TOTAL rate (n = hg + ag is
Poisson(lt)), the fit decouples: first solve lt from the over probability, then
solve the home share from the AH probability at that total.
"""
from __future__ import annotations

import math


def components(line: float) -> list[tuple[float, float]]:
    """[(component line, stake weight)] - a quarter line is split in two."""
    q = round(line * 4)
    if q % 2 != 0:
        return [(line - 0.25, 0.5), (line + 0.25, 0.5)]
    return [(line, 1.0)]


def _pmf(lam: float, n_max: int) -> list[float]:
    p = [math.exp(-lam)]
    for k in range(1, n_max + 1):
        p.append(p[-1] * lam / k)
    return p


def _two_way_prob(dist: dict[float, float], line: float, sign: float) -> float:
    """dist maps an integer outcome (goal margin, or total goals) to probability.
    sign=+1: a bet that wins when outcome + line > 0 (home AH); sign=-1 for
    totals handled by the caller via a shifted line."""
    win = push = 0.0
    for c, w in components(line):
        for x, p in dist.items():
            v = x + c
            if v > 1e-9:
                win += w * p
            elif abs(v) <= 1e-9:
                push += w * p
    denom = 1.0 - push
    return win / denom if denom > 1e-12 else float("nan")


def over_prob(lt: float, total_line: float) -> float:
    n_max = int(lt + 8 * math.sqrt(lt) + 10)
    dist = {n: p for n, p in enumerate(_pmf(lt, n_max))}
    # over wins when n - line > 0  <=> n + (-line) > 0
    return _two_way_prob(dist, -total_line, 1.0)


def home_cover_prob(lh: float, la: float, ah_line: float) -> float:
    n_h = int(lh + 8 * math.sqrt(max(lh, 1e-9)) + 10)
    n_a = int(la + 8 * math.sqrt(max(la, 1e-9)) + 10)
    ph, pa = _pmf(lh, n_h), _pmf(la, n_a)
    dist: dict[float, float] = {}
    for i, a in enumerate(ph):
        for j, b in enumerate(pa):
            dist[i - j] = dist.get(i - j, 0.0) + a * b
    return _two_way_prob(dist, ah_line, 1.0)


def _solve(f, lo: float, hi: float, tol: float = 1e-10, max_iter: int = 80):
    """Root of an increasing function f on [lo, hi] (Illinois false position).
    Returns (x, bracketed). If the root is outside, returns the nearer end."""
    flo, fhi = f(lo), f(hi)
    if flo > 0:
        return lo, False
    if fhi < 0:
        return hi, False
    side = 0
    x = lo
    for _ in range(max_iter):
        x = (lo * fhi - hi * flo) / (fhi - flo) if fhi != flo else 0.5 * (lo + hi)
        fx = f(x)
        if abs(fx) < tol or (hi - lo) < 1e-12:
            return x, True
        if fx > 0:
            hi, fhi = x, fx
            if side == 1:
                flo *= 0.5
            side = 1
        else:
            lo, flo = x, fx
            if side == -1:
                fhi *= 0.5
            side = -1
    return x, True


def fit(ah_line: float, p_ah_home: float, total_line: float, p_over: float) -> dict:
    """Returns {"lh","la","supremacy","total","ok"}; ok is False if either target
    was outside what the model can reach (the value is then clipped)."""
    lt, ok1 = _solve(lambda x: over_prob(x, total_line) - p_over, 0.05, 15.0)
    eps = 1e-4
    lh, ok2 = _solve(lambda x: home_cover_prob(x, lt - x, ah_line) - p_ah_home, eps, lt - eps)
    la = lt - lh
    return {"lh": lh, "la": la, "supremacy": lh - la, "total": lt, "ok": ok1 and ok2}
