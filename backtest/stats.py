"""Bootstrap that resamples WHOLE matches (several flags in one match are not independent)."""
from __future__ import annotations

import math
import random


class Boot:
    def __init__(self, match_keys: list[str], B: int, seed: int):
        self.keys = list(match_keys)
        self.index = {k: i for i, k in enumerate(self.keys)}
        m = len(self.keys)
        rnd = random.Random(seed)
        self.draws = [[rnd.randrange(m) for _ in range(m)] for _ in range(B)]
        self.m = m

    def agg(self, events: list[dict], value) -> tuple[list[float], list[int]]:
        s = [0.0] * self.m
        n = [0] * self.m
        for e in events:
            v = value(e)
            if v is None:
                continue
            i = self.index[e["match"]]
            s[i] += v
            n[i] += 1
        return s, n

    def mean(self, events: list[dict], value) -> dict:
        s, n = self.agg(events, value)
        tot_n = sum(n)
        if tot_n == 0:
            return {"n": 0, "matches": 0, "mean": None, "lo": None, "hi": None, "boot": []}
        point = sum(s) / tot_n
        boots = []
        for d in self.draws:
            sn = sum(n[i] for i in d)
            if sn:
                boots.append(sum(s[i] for i in d) / sn)
        boots.sort()
        lo, hi = _pct(boots, 0.025), _pct(boots, 0.975)
        return {"n": tot_n, "matches": sum(1 for x in n if x), "mean": point, "lo": lo, "hi": hi, "boot": boots}

    def diff(self, events_a, events_b, value_a, value_b=None) -> dict:
        """mean(a) - mean(b), sharing the same match resamples."""
        value_b = value_b or value_a
        sa, na = self.agg(events_a, value_a)
        sb, nb = self.agg(events_b, value_b)
        if sum(na) == 0 or sum(nb) == 0:
            return {"diff": None, "lo": None, "hi": None}
        point = sum(sa) / sum(na) - sum(sb) / sum(nb)
        boots = []
        for d in self.draws:
            x, y = sum(na[i] for i in d), sum(nb[i] for i in d)
            if x and y:
                boots.append(sum(sa[i] for i in d) / x - sum(sb[i] for i in d) / y)
        boots.sort()
        return {"diff": point, "lo": _pct(boots, 0.025), "hi": _pct(boots, 0.975)}

    def slope(self, events: list[dict], x, y) -> dict:
        """OLS slope of y on x over events, with a match-level bootstrap interval."""
        keys = ("n", "sx", "sy", "sxy", "sxx")
        a = {k: [0.0] * self.m for k in keys}
        for e in events:
            xv, yv = x(e), y(e)
            if xv is None or yv is None:
                continue
            i = self.index[e["match"]]
            a["n"][i] += 1; a["sx"][i] += xv; a["sy"][i] += yv; a["sxy"][i] += xv * yv; a["sxx"][i] += xv * xv

        def calc(idx):
            n = sum(a["n"][i] for i in idx)
            if n < 3:
                return None
            sx = sum(a["sx"][i] for i in idx); sy = sum(a["sy"][i] for i in idx)
            sxy = sum(a["sxy"][i] for i in idx); sxx = sum(a["sxx"][i] for i in idx)
            den = n * sxx - sx * sx
            return (n * sxy - sx * sy) / den if abs(den) > 1e-12 else None

        point = calc(range(self.m))
        boots = sorted(v for v in (calc(d) for d in self.draws) if v is not None)
        return {"n": int(sum(a["n"])), "slope": point, "lo": _pct(boots, 0.025), "hi": _pct(boots, 0.975)}


def _pct(sorted_vals: list[float], q: float):
    if not sorted_vals:
        return None
    i = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[i]


def bucket_of(x: float, edges) -> int:
    for i in range(len(edges) - 1):
        if edges[i] <= x < edges[i + 1]:
            return i
    return len(edges) - 2


def bucket_label(i: int, edges) -> str:
    lo, hi = edges[i], edges[i + 1]
    return f"{lo:g}+" if hi == math.inf else f"{lo:g}-{hi:g}"
