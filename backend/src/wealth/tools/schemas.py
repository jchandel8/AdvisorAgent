"""Input models for the tools: what the MODEL is allowed to send.

advisor_id is deliberately absent. extra="forbid" means a model that tries to send advisor_id
(or any unknown field) gets a validation error and the tool never runs.
"""

from __future__ import annotations

from datetime import date
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Must match the lookup tables (sectors, asset_classes, currencies); tests/test_schema.py checks this.
Sector = Literal[
    "Technology",
    "Health Care",
    "Financials",
    "Consumer Discretionary",
    "Consumer Staples",
    "Energy",
    "Industrials",
    "Utilities",
    "Communication Services",
    "Real Estate",
    "Materials",
    "Fixed Income",
    "Cash",
]
AssetClass = Literal["equity", "fixed_income", "cash"]
Currency = Literal["USD"]
SECTORS: tuple[str, ...] = get_args(Sector)
ASSET_CLASSES: tuple[str, ...] = get_args(AssetClass)
CURRENCIES: tuple[str, ...] = get_args(Currency)


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoInput(ToolInput):
    pass


class ClientInput(ToolInput):
    client_id: int = Field(gt=0, description="ID of the client (from get_my_clients).")


class ScopeInput(ToolInput):
    account_id: int | None = Field(default=None, gt=0, description="One account. Give this OR client_id.")
    client_id: int | None = Field(
        default=None,
        gt=0,
        description="All accounts of this client that you can access. Give this OR account_id.",
    )

    @model_validator(mode="after")
    def _exactly_one_scope(self):
        if (self.account_id is None) == (self.client_id is None):
            raise ValueError("give exactly one of account_id or client_id")
        return self


class SecurityFilters(ToolInput):
    """Optional filters on the securities involved. Omit a filter to include everything."""

    sectors: list[Sector] | None = Field(default=None, min_length=1, description="Only these sectors.")
    asset_classes: list[AssetClass] | None = Field(
        default=None, min_length=1, description="Only these asset classes."
    )
    currencies: list[Currency] | None = Field(
        default=None, min_length=1, description="Only securities priced in these currencies."
    )

    def filter_params(self) -> dict:
        return {"sectors": self.sectors, "asset_classes": self.asset_classes, "currencies": self.currencies}


class HoldingsInput(ScopeInput, SecurityFilters):
    as_of_date: date | None = Field(
        default=None,
        description="YYYY-MM-DD. Uses the latest snapshot on or before this date. Default: today.",
    )
    detail: Literal["totals", "summary", "full"] = Field(
        default="summary",
        description=(
            "totals: totals and sector/asset-class breakdown only, no positions (best when screening many "
            "clients). summary (default): totals, breakdowns and the 10 largest positions. "
            "full: every position; use only when the advisor asks about individual positions."
        ),
    )


class PerformanceInput(ScopeInput):
    as_of_date: date | None = Field(
        default=None,
        description="YYYY-MM-DD. Uses the latest figures on or before this date. Default: today.",
    )


class TransactionsInput(ScopeInput, SecurityFilters):
    types: list[Literal["buy", "sell", "dividend", "deposit", "withdrawal"]] | None = Field(
        default=None, min_length=1, description="Only these transaction types (e.g. buy and sell)."
    )
    start_date: date | None = Field(default=None, description="YYYY-MM-DD. Default: 90 days before end_date.")
    end_date: date | None = Field(default=None, description="YYYY-MM-DD. Default: today.")

    @model_validator(mode="after")
    def _ordered(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self


class ReviewsInput(ToolInput):
    within_days: int = Field(
        ge=0,
        le=365,
        description="Reviews due from today through today + within_days. Overdue reviews are included.",
    )


class DocumentSearchInput(ToolInput):
    query: str = Field(
        min_length=2,
        max_length=200,
        description='Words to look for, e.g. "rebalance college savings". Quotes match a phrase; -word excludes.',
    )
    account_id: int | None = Field(default=None, gt=0, description="Only this account's documents.")
    client_id: int | None = Field(default=None, gt=0, description="Only documents on this client's accounts.")
    limit: int = Field(default=5, ge=1, le=10, description="Most results to return (best matches first).")

    @model_validator(mode="after")
    def _at_most_one_scope(self):
        if self.account_id is not None and self.client_id is not None:
            raise ValueError("give account_id or client_id, not both")
        if not self.query.strip():
            raise ValueError("query must contain words")
        return self
