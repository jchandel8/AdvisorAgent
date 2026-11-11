"""About 60 real securities. Prices are SIMULATED (seeded), not market data.

Fields: symbol, description, sector, asset_class, start_price (7 years before the anchor date),
annual_drift, annual_vol, dividend_yield.
"""

from __future__ import annotations

from dataclasses import dataclass

TECH = "Technology"


@dataclass(frozen=True)
class Security:
    symbol: str
    description: str
    sector: str
    asset_class: str
    start_price: float
    drift: float
    vol: float
    dividend_yield: float


def _eq(symbol, description, sector, price, drift, vol, dy):
    return Security(symbol, description, sector, "equity", price, drift, vol, dy)


def _fi(symbol, description, price, vol, dy):
    return Security(symbol, description, "Fixed Income", "fixed_income", price, 0.0, vol, dy)


SECURITIES: list[Security] = [
    # Technology
    _eq("AAPL", "Apple Inc.", TECH, 45, 0.20, 0.28, 0.006),
    _eq("MSFT", "Microsoft Corp.", TECH, 105, 0.18, 0.25, 0.008),
    _eq("NVDA", "NVIDIA Corp.", TECH, 40, 0.30, 0.50, 0.001),
    _eq("GOOGL", "Alphabet Inc. Class A", TECH, 55, 0.15, 0.28, 0.002),
    _eq("META", "Meta Platforms Inc.", TECH, 160, 0.15, 0.40, 0.003),
    _eq("AVGO", "Broadcom Inc.", TECH, 30, 0.25, 0.35, 0.015),
    _eq("ORCL", "Oracle Corp.", TECH, 50, 0.15, 0.30, 0.012),
    _eq("CRM", "Salesforce Inc.", TECH, 150, 0.08, 0.32, 0.004),
    _eq("ADBE", "Adobe Inc.", TECH, 260, 0.05, 0.32, 0.0),
    _eq("AMD", "Advanced Micro Devices Inc.", TECH, 25, 0.22, 0.50, 0.0),
    _eq("CSCO", "Cisco Systems Inc.", TECH, 45, 0.05, 0.22, 0.03),
    _eq("INTC", "Intel Corp.", TECH, 50, -0.08, 0.35, 0.02),
    _eq("QCOM", "Qualcomm Inc.", TECH, 60, 0.12, 0.32, 0.02),
    _eq("TXN", "Texas Instruments Inc.", TECH, 105, 0.07, 0.25, 0.028),
    _eq("IBM", "International Business Machines", TECH, 120, 0.09, 0.22, 0.04),
    # Health Care
    _eq("JNJ", "Johnson & Johnson", "Health Care", 130, 0.03, 0.15, 0.03),
    _eq("UNH", "UnitedHealth Group Inc.", "Health Care", 240, 0.08, 0.24, 0.015),
    _eq("PFE", "Pfizer Inc.", "Health Care", 40, -0.05, 0.22, 0.05),
    _eq("MRK", "Merck & Co. Inc.", "Health Care", 75, 0.05, 0.20, 0.03),
    _eq("ABBV", "AbbVie Inc.", "Health Care", 80, 0.12, 0.22, 0.04),
    _eq("LLY", "Eli Lilly and Co.", "Health Care", 110, 0.28, 0.30, 0.008),
    _eq("TMO", "Thermo Fisher Scientific Inc.", "Health Care", 230, 0.08, 0.24, 0.003),
    # Financials
    _eq("JPM", "JPMorgan Chase & Co.", "Financials", 100, 0.12, 0.24, 0.025),
    _eq("BAC", "Bank of America Corp.", "Financials", 28, 0.08, 0.28, 0.025),
    _eq("WFC", "Wells Fargo & Co.", "Financials", 50, 0.06, 0.30, 0.025),
    _eq("GS", "Goldman Sachs Group Inc.", "Financials", 200, 0.14, 0.28, 0.025),
    _eq("MS", "Morgan Stanley", "Financials", 45, 0.13, 0.28, 0.03),
    _eq("V", "Visa Inc. Class A", "Financials", 140, 0.12, 0.20, 0.008),
    _eq("MA", "Mastercard Inc. Class A", "Financials", 200, 0.13, 0.22, 0.006),
    _eq("BRK.B", "Berkshire Hathaway Inc. Class B", "Financials", 200, 0.11, 0.17, 0.0),
    # Consumer Discretionary
    _eq("AMZN", "Amazon.com Inc.", "Consumer Discretionary", 90, 0.14, 0.32, 0.0),
    _eq("TSLA", "Tesla Inc.", "Consumer Discretionary", 20, 0.25, 0.60, 0.0),
    _eq("HD", "Home Depot Inc.", "Consumer Discretionary", 180, 0.09, 0.22, 0.024),
    _eq("MCD", "McDonald's Corp.", "Consumer Discretionary", 170, 0.07, 0.17, 0.022),
    _eq("NKE", "Nike Inc. Class B", "Consumer Discretionary", 75, -0.02, 0.30, 0.018),
    _eq("SBUX", "Starbucks Corp.", "Consumer Discretionary", 60, 0.04, 0.27, 0.025),
    # Consumer Staples
    _eq("PG", "Procter & Gamble Co.", "Consumer Staples", 90, 0.07, 0.15, 0.024),
    _eq("KO", "Coca-Cola Co.", "Consumer Staples", 45, 0.06, 0.15, 0.03),
    _eq("PEP", "PepsiCo Inc.", "Consumer Staples", 110, 0.05, 0.16, 0.03),
    _eq("WMT", "Walmart Inc.", "Consumer Staples", 30, 0.13, 0.18, 0.013),
    _eq("COST", "Costco Wholesale Corp.", "Consumer Staples", 200, 0.18, 0.20, 0.006),
    # Energy
    _eq("XOM", "Exxon Mobil Corp.", "Energy", 75, 0.06, 0.28, 0.035),
    _eq("CVX", "Chevron Corp.", "Energy", 110, 0.05, 0.28, 0.04),
    _eq("COP", "ConocoPhillips", "Energy", 60, 0.09, 0.33, 0.03),
    # Industrials
    _eq("CAT", "Caterpillar Inc.", "Industrials", 130, 0.16, 0.28, 0.018),
    _eq("HON", "Honeywell International Inc.", "Industrials", 150, 0.06, 0.20, 0.02),
    _eq("UNP", "Union Pacific Corp.", "Industrials", 150, 0.07, 0.22, 0.022),
    _eq("BA", "Boeing Co.", "Industrials", 330, -0.08, 0.38, 0.0),
    _eq("GE", "GE Aerospace", "Industrials", 50, 0.18, 0.33, 0.006),
    # Utilities
    _eq("NEE", "NextEra Energy Inc.", "Utilities", 45, 0.06, 0.22, 0.028),
    _eq("DUK", "Duke Energy Corp.", "Utilities", 85, 0.04, 0.16, 0.04),
    _eq("SO", "Southern Co.", "Utilities", 50, 0.07, 0.16, 0.035),
    # Communication Services
    _eq("DIS", "Walt Disney Co.", "Communication Services", 110, -0.01, 0.28, 0.008),
    _eq("NFLX", "Netflix Inc.", "Communication Services", 300, 0.15, 0.40, 0.0),
    _eq("VZ", "Verizon Communications Inc.", "Communication Services", 55, -0.03, 0.17, 0.065),
    _eq("T", "AT&T Inc.", "Communication Services", 20, 0.02, 0.22, 0.05),
    # Real Estate and Materials
    _eq("PLD", "Prologis Inc.", "Real Estate", 70, 0.07, 0.25, 0.03),
    _eq("AMT", "American Tower Corp.", "Real Estate", 170, 0.02, 0.25, 0.03),
    _eq("LIN", "Linde plc", "Materials", 170, 0.13, 0.20, 0.012),
    # Fixed income ETFs
    _fi("AGG", "iShares Core US Aggregate Bond ETF", 105, 0.05, 0.033),
    _fi("BND", "Vanguard Total Bond Market ETF", 80, 0.05, 0.033),
    _fi("TLT", "iShares 20+ Year Treasury Bond ETF", 120, 0.14, 0.038),
    _fi("LQD", "iShares iBoxx Investment Grade Corporate Bond ETF", 115, 0.08, 0.042),
    _fi("MUB", "iShares National Muni Bond ETF", 108, 0.04, 0.028),
    _fi("SHY", "iShares 1-3 Year Treasury Bond ETF", 84, 0.015, 0.035),
    # Cash (uninvested balance; price is always 1)
    Security("CASH", "Cash and sweep balance", "Cash", "cash", 1.0, 0.0, 0.0, 0.0),
]

BY_SYMBOL = {s.symbol: s for s in SECURITIES}
EQUITIES = [s for s in SECURITIES if s.asset_class == "equity"]
FIXED_INCOME = [s for s in SECURITIES if s.asset_class == "fixed_income"]
