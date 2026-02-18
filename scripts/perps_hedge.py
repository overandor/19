from __future__ import annotations

from decimal import Decimal, getcontext
from typing import Dict

getcontext().prec = 40

HOURS_PER_YEAR = Decimal(24 * 365)


def _to_decimal(value, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    return Decimal(str(value))


def compute_perps_hedge(
    buy_price: float,
    sell_price: float,
    *,
    spot_notional_usd: float,
    dex_fees_bps_roundtrip: float,
    slip_bps: float,
    buffer_bps: float,
    perp_taker_bps_roundtrip: float,
    funding_rate_bps_8h: float,
    borrow_apr_bps: float,
    expected_hold_hours: float,
) -> Dict[str, float | None]:
    """Deterministic DEX spot + perp short hedge economics.

    Returns all values as floats for JSON serialization.
    """
    buy = _to_decimal(buy_price)
    sell = _to_decimal(sell_price)
    notional = _to_decimal(spot_notional_usd)

    if buy <= 0 or sell <= 0 or notional <= 0:
        return {
            "spot_notional_usd": float(notional),
            "base_units": 0.0,
            "gross_spread_usd": 0.0,
            "costs_usd": {
                "spot_execution": 0.0,
                "perp_execution": 0.0,
                "funding": 0.0,
                "borrow": 0.0,
                "total": 0.0,
            },
            "net_hedged_pnl_usd": 0.0,
            "net_hedged_edge_bps": -1e9,
            "break_even_hold_hours": 0.0,
        }

    units = notional / buy
    gross_spread_usd = (sell - buy) * units

    spot_cost_bps = _to_decimal(dex_fees_bps_roundtrip) + _to_decimal(slip_bps) + _to_decimal(buffer_bps)
    spot_cost_usd = notional * spot_cost_bps / Decimal(1e4)

    perp_cost_usd = notional * _to_decimal(perp_taker_bps_roundtrip) / Decimal(1e4)

    hold_hours = _to_decimal(expected_hold_hours)
    funding_cost_usd = (
        notional
        * _to_decimal(funding_rate_bps_8h)
        / Decimal(1e4)
        * (hold_hours / Decimal(8))
    )
    borrow_cost_usd = (
        notional
        * _to_decimal(borrow_apr_bps)
        / Decimal(1e4)
        * (hold_hours / HOURS_PER_YEAR)
    )

    total_cost_usd = spot_cost_usd + perp_cost_usd + funding_cost_usd + borrow_cost_usd
    net_pnl_usd = gross_spread_usd - total_cost_usd
    net_edge_bps = net_pnl_usd / notional * Decimal(1e4)

    remaining_before_time_decay = gross_spread_usd - (spot_cost_usd + perp_cost_usd)
    hourly_time_decay_usd = notional * (
        (_to_decimal(funding_rate_bps_8h) / Decimal(8))
        + (_to_decimal(borrow_apr_bps) / HOURS_PER_YEAR)
    ) / Decimal(1e4)

    if hourly_time_decay_usd <= 0:
        break_even_hold_hours = None
    else:
        break_even_hold_hours = float(remaining_before_time_decay / hourly_time_decay_usd)

    return {
        "spot_notional_usd": float(notional),
        "base_units": float(units),
        "gross_spread_usd": float(gross_spread_usd),
        "costs_usd": {
            "spot_execution": float(spot_cost_usd),
            "perp_execution": float(perp_cost_usd),
            "funding": float(funding_cost_usd),
            "borrow": float(borrow_cost_usd),
            "total": float(total_cost_usd),
        },
        "net_hedged_pnl_usd": float(net_pnl_usd),
        "net_hedged_edge_bps": float(net_edge_bps),
        "break_even_hold_hours": break_even_hold_hours,
    }
