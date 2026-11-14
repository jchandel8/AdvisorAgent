"""Analytics MCP server: portfolio calculations on numbers passed in.

Pure functions: no database, nothing stored, the same answer for the same input. They exist so the model
never does arithmetic itself (the same rule as "math in SQL" for the data tools). The model passes numbers
it got from the Portfolio tools; the results are exact and testable.

Built with the SDK's decorator API (MCPServer), which reads each tool's JSON schema from the function's type
hints. The Portfolio server uses the low-level API instead, because its schemas already exist.
"""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from wealth.mcp.guard import InternalOnly

NAME = "advisoragent-analytics"

Pct = Annotated[float, Field(ge=0, le=100)]
ClassWeights = Annotated[dict[str, Pct], Field(min_length=1, max_length=20)]


def _r(x: float, places: int = 2) -> float:
    return round(x + 0.0, places)  # + 0.0 turns -0.0 into 0.0


def allocation_drift(
    current_pct: dict[str, float], target_pct: dict[str, float], threshold_pct: float = 5
) -> dict:
    """Current vs target weight per asset class, in percentage points."""
    classes = sorted(set(current_pct) | set(target_pct))
    rows = []
    for name in classes:
        cur, tgt = current_pct.get(name, 0.0), target_pct.get(name, 0.0)
        drift = cur - tgt
        rows.append(
            {
                "asset_class": name,
                "current_pct": _r(cur),
                "target_pct": _r(tgt),
                "drift_pct": _r(drift),
                "outside_band": abs(drift) > threshold_pct,
            }
        )
    total = sum(abs(r["drift_pct"]) for r in rows) / 2  # the share of the portfolio that would have to move
    return {
        "threshold_pct": threshold_pct,
        "classes": rows,
        "total_drift_pct": _r(total),
        "needs_rebalance": any(r["outside_band"] for r in rows),
    }


def concentration(weights_pct: dict[str, float], single_position_limit_pct: float = 10) -> dict:
    """How concentrated a portfolio is: HHI, effective number of positions, top-N shares, large positions."""
    ordered = sorted(weights_pct.items(), key=lambda kv: (-kv[1], kv[0]))
    hhi = sum((w / 100) ** 2 for _, w in ordered) * 10_000
    return {
        "positions": len(ordered),
        "hhi": _r(hhi, 0),
        "effective_positions": _r(10_000 / hhi, 1) if hhi else 0.0,
        "top_1_pct": _r(sum(w for _, w in ordered[:1])),
        "top_5_pct": _r(sum(w for _, w in ordered[:5])),
        "top_10_pct": _r(sum(w for _, w in ordered[:10])),
        "over_limit": [{"name": n, "weight_pct": _r(w)} for n, w in ordered if w > single_position_limit_pct],
        "single_position_limit_pct": single_position_limit_pct,
    }


def rebalance_preview(
    total_value: float, current_pct: dict[str, float], target_pct: dict[str, float]
) -> dict:
    """Dollar amount to move per asset class to reach the target (positive = buy, negative = sell).

    A preview for the advisor's review, not an order. Amounts add up to zero (cents included).
    """
    classes = sorted(set(current_pct) | set(target_pct))
    moves = []
    for name in classes:
        amount = total_value * (target_pct.get(name, 0.0) - current_pct.get(name, 0.0)) / 100
        moves.append({"asset_class": name, "amount": _r(amount)})
    rounding = _r(-sum(m["amount"] for m in moves))  # put the cent left over by rounding on the largest move
    if moves and rounding:
        biggest = max(moves, key=lambda m: abs(m["amount"]))
        biggest["amount"] = _r(biggest["amount"] + rounding)
    return {
        "total_value": _r(total_value),
        "moves": moves,
        "turnover": _r(sum(m["amount"] for m in moves if m["amount"] > 0)),
    }


server = MCPServer(NAME, version="1", instructions="Pure portfolio calculations. Percent inputs are 0-100.")


@server.tool(name="allocation_drift")
def _allocation_drift(
    current_pct: ClassWeights,
    target_pct: ClassWeights,
    threshold_pct: Annotated[float, Field(gt=0, le=50)] = 5,
) -> dict:
    """Compare current and target weights per asset class (percent, 0-100). Returns the drift of each class in
    percentage points, which classes are outside the band, and the total share of the portfolio that would
    have to move."""
    return allocation_drift(current_pct, target_pct, threshold_pct)


@server.tool(name="concentration")
def _concentration(
    weights_pct: Annotated[dict[str, Pct], Field(min_length=1, max_length=500)],
    single_position_limit_pct: Annotated[float, Field(gt=0, le=100)] = 10,
) -> dict:
    """Measure concentration from position weights (symbol -> percent, 0-100): HHI, effective number of
    positions, top 1/5/10 share, and positions above the single-position limit."""
    return concentration(weights_pct, single_position_limit_pct)


@server.tool(name="rebalance_preview")
def _rebalance_preview(
    total_value: Annotated[float, Field(gt=0)],
    current_pct: ClassWeights,
    target_pct: ClassWeights,
) -> dict:
    """Dollar amount to buy (positive) or sell (negative) in each asset class to reach the target weights.
    A preview for the advisor, not an order."""
    return rebalance_preview(total_value, current_pct, target_pct)


def asgi_app():
    inner = server.streamable_http_app(streamable_http_path="/", stateless_http=True, json_response=True)
    return InternalOnly(inner, "analytics"), inner
