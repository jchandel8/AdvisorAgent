"""get_holdings: positions for one account or for all of a client's accessible accounts.

Optional filters (sector, asset class, currency) are applied in SQL, so only matching positions are
returned. Every figure is given both as a share of the selection and of the whole portfolio in scope.
detail: "totals" (no positions), "summary" (default: the 10 largest positions) or "full" (every position).
"""

from __future__ import annotations

from wealth.access import NOT_FOUND, SCOPED, VISIBLE, ToolContext, scoped_account_ids, snapshot_sql
from wealth.tools.schemas import HoldingsInput

SUMMARY_TOP_N = 10

# portfolio = every position in scope; selection = positions that pass the filters.
_BASE = f"""
WITH {VISIBLE}, {SCOPED}, {snapshot_sql("scoped")},
positions AS (
    SELECT h.symbol, s.description, s.sector, s.asset_class, s.currency::text AS currency,
           sum(h.quantity) AS quantity,
           sum(h.quantity * h.price) AS mv,
           sum(h.cost_basis) AS cost
    FROM holdings h
    JOIN snapshot sn ON sn.account_id = h.account_id AND sn.as_of_date = h.as_of_date
    JOIN securities s ON s.symbol = h.symbol
    GROUP BY h.symbol, s.description, s.sector, s.asset_class, s.currency
),
portfolio AS (
    SELECT coalesce(sum(mv), 0) AS mv FROM positions
),
selection AS (
    SELECT * FROM positions
    WHERE (%(sectors)s::text[] IS NULL OR sector = ANY(%(sectors)s::text[]))
      AND (%(asset_classes)s::text[] IS NULL OR asset_class = ANY(%(asset_classes)s::text[]))
      AND (%(currencies)s::text[] IS NULL OR currency = ANY(%(currencies)s::text[]))
)"""

# One pass gives the sector rows, the asset-class rows and the selection total (the () grouping set).
_SUMMARY = (
    _BASE
    + """
SELECT GROUPING(x.sector) AS g_sector,
       GROUPING(x.asset_class) AS g_asset_class,
       x.sector,
       x.asset_class,
       count(x.symbol) AS positions,
       round(coalesce(sum(x.mv), 0), 2) AS market_value,
       round(coalesce(sum(x.cost), 0), 2) AS cost_basis,
       round(coalesce(sum(x.mv) - sum(x.cost), 0), 2) AS unrealized_gain,
       round(100 * sum(x.mv) / nullif(sum(sum(x.mv)) OVER (
           PARTITION BY GROUPING(x.sector), GROUPING(x.asset_class)), 0), 2) AS pct_of_selection,
       round(100 * coalesce(sum(x.mv), 0) / nullif(max(p.mv), 0), 2) AS pct_of_portfolio,
       round(max(p.mv), 2) AS portfolio_market_value
FROM portfolio p
LEFT JOIN selection x ON true
GROUP BY GROUPING SETS ((x.sector), (x.asset_class), ())
ORDER BY sum(x.mv) DESC NULLS LAST"""
)

_POSITIONS = (
    _BASE
    + """
SELECT x.symbol, x.description, x.sector, x.asset_class, x.currency,
       round(x.quantity, 4) AS quantity,
       round(x.mv / nullif(x.quantity, 0), 4) AS price,
       round(x.mv, 2) AS market_value,
       round(x.cost, 2) AS cost_basis,
       round(x.mv - x.cost, 2) AS unrealized_gain,
       round(100 * x.mv / nullif(sum(x.mv) OVER (), 0), 2) AS pct_of_selection,
       round(100 * x.mv / nullif(p.mv, 0), 2) AS pct_of_portfolio
FROM selection x
CROSS JOIN portfolio p
ORDER BY x.mv DESC, x.symbol
LIMIT %(limit)s"""
)

_ACCOUNTS = f"""
WITH {VISIBLE}, {SCOPED}, {snapshot_sql("scoped")}
SELECT sc.account_id, a.account_name, m.as_of_date, round(coalesce(m.market_value, 0), 2) AS market_value
FROM scoped sc
JOIN accounts a ON a.id = sc.account_id
LEFT JOIN account_mv m ON m.account_id = sc.account_id
ORDER BY sc.account_id"""


def get_holdings(ctx: ToolContext, params: HoldingsInput) -> dict:
    ids = scoped_account_ids(ctx, account_id=params.account_id, client_id=params.client_id)
    if not ids:
        return NOT_FOUND
    q = {
        "advisor_id": ctx.advisor_id,
        "ids": ids,
        "as_of": params.as_of_date or ctx.today,
        **params.filter_params(),
        "limit": {"totals": 0, "summary": SUMMARY_TOP_N, "full": None}[params.detail],  # LIMIT NULL = all
    }

    sectors, asset_classes, total = [], [], {}
    for row in ctx.conn.execute(_SUMMARY, q).fetchall():
        g_sector, g_class = row.pop("g_sector"), row.pop("g_asset_class")
        if g_sector and g_class:  # the () grouping set: selection total
            total = {k: v for k, v in row.items() if k not in ("sector", "asset_class")}
        elif row["positions"] == 0:  # an empty selection still yields one NULL group per grouping set
            continue
        elif not g_sector:
            sectors.append(
                {k: v for k, v in row.items() if k not in ("asset_class", "portfolio_market_value")}
            )
        else:
            asset_classes.append(
                {k: v for k, v in row.items() if k not in ("sector", "portfolio_market_value")}
            )

    positions = ctx.conn.execute(_POSITIONS, q).fetchall()
    filters = {k: v for k, v in params.filter_params().items() if v is not None}
    return {
        "scope": {"account_id": params.account_id, "client_id": params.client_id},
        "filters": filters or "none",
        "accounts": ctx.conn.execute(_ACCOUNTS, q).fetchall(),
        "portfolio_market_value": total.pop("portfolio_market_value"),
        "selection": total,
        "sector_summary": sectors,
        "asset_class_summary": asset_classes,
        "detail": params.detail,
        "positions_returned": len(positions),
        "holdings": positions,
    }
