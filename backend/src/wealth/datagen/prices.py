"""Seeded, simulated price history.

Prices are defined on a grid of dates that are whole months before the anchor date
(anchor, anchor-1m, anchor-2m, ... anchor-84m). Between grid dates the price is a straight line,
so any trade date has a price. Prices on grid dates are rounded to cents.
"""

from __future__ import annotations

import bisect
import math
import random
from datetime import date, timedelta

from wealth.datagen.securities import SECURITIES, Security

HISTORY_MONTHS = 84  # enough for a 5-year return on the oldest (23-month-old) performance row


def months_before(d: date, n: int) -> date:
    """Same day-of-month n months earlier, clamped to the month's last day (e.g. Mar 31 - 1m = Feb 28)."""
    y, m = divmod(d.year * 12 + (d.month - 1) - n, 12)
    m += 1
    if m == 12:
        last = 31
    else:
        last = (date(y, m + 1, 1) - timedelta(days=1)).day
    return date(y, m, min(d.day, last))


class PriceBook:
    def __init__(self, anchor: date, rng: random.Random, seed: int, securities: list[Security] = SECURITIES):
        self.anchor = anchor
        self.seed = seed
        self.grid: list[date] = [months_before(anchor, n) for n in range(HISTORY_MONTHS, -1, -1)]
        self._prices: dict[str, list[float]] = {}

        dt = 1 / 12
        for sec in securities:
            if sec.asset_class == "cash":
                self._prices[sec.symbol] = [1.0] * len(self.grid)
                continue
            # Geometric random walk; a shared "market" shock makes equities move together.
            path = [sec.start_price]
            for _ in self.grid[1:]:
                market = rng.gauss(0, 1)
                own = rng.gauss(0, 1)
                beta = 0.7 if sec.asset_class == "equity" else 0.2
                z = beta * market + math.sqrt(1 - beta * beta) * own
                step = (sec.drift - 0.5 * sec.vol**2) * dt + sec.vol * math.sqrt(dt) * z
                path.append(path[-1] * math.exp(step))
            self._prices[sec.symbol] = [max(round(p, 2), 0.01) for p in path]
        self._vol = {sec.symbol: sec.vol for sec in securities}

    def price(self, symbol: str, d: date) -> float:
        """Price on any date within the grid (linear between grid dates), rounded to cents."""
        prices = self._prices[symbol]
        if d <= self.grid[0]:
            return prices[0]
        if d >= self.grid[-1]:
            return prices[-1]
        i = bisect.bisect_right(self.grid, d)
        d0, d1 = self.grid[i - 1], self.grid[i]
        if d == d0:
            return prices[i - 1]
        w = (d - d0).days / (d1 - d0).days
        return max(round(prices[i - 1] + w * (prices[i] - prices[i - 1]), 2), 0.01)

    def prev_day_price(self, symbol: str, d: date) -> float:
        """Price the day before d, with a small seeded daily move so 1-day returns are not flat."""
        base = self.price(symbol, d - timedelta(days=1))
        if symbol == "CASH":
            return base
        # A string seed is hashed deterministically, so the same (seed, symbol, date) always gives the same move.
        move = random.Random(f"{self.seed}:{symbol}:{d.isoformat()}").gauss(
            0, self._vol[symbol] / math.sqrt(252)
        )
        return max(round(base / (1 + move), 2), 0.01)
