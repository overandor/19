#!/usr/bin/env python3
"""Research-only perpetual futures watcher for Gate.io + Binance.

Purpose:
- Poll public market-data endpoints (no exchange API keys required).
- Emit research alerts as GitHub issues/comments.
- Never produce executable trade instructions.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

GITHUB_API = "https://api.github.com"
BINANCE_FAPI = "https://fapi.binance.com"
GATE_REST = "https://api.gateio.ws/api/v4"

ALERT_LABEL = "research-alert"
ISSUE_TITLE_PREFIX = "Research alert:"

# Research-only watch thresholds (tunable).
PRICE_MOVE_THRESHOLD_PCT = 1.0
RANGE_THRESHOLD_PCT = 1.5
FUNDING_ABS_THRESHOLD = 0.0005
SPREAD_THRESHOLD_BPS = 8.0

BINANCE_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
GATE_CONTRACTS = ["BTC_USDT", "ETH_USDT", "SOL_USDT"]

HISTORY_DIR = Path("alerts/history")


@dataclass
class Alert:
    exchange: str
    symbol: str
    reasons: List[str]
    metrics: Dict[str, Any]

    @property
    def title(self) -> str:
        return f"{ISSUE_TITLE_PREFIX} {self.exchange} {self.symbol}"

    def render_body(self) -> str:
        reasons_text = "\n".join(f"- {r}" for r in self.reasons)
        return (
            f"Research alert for `{self.exchange}:{self.symbol}`.\n\n"
            "Reason:\n"
            f"{reasons_text}\n\n"
            "Interpretation:\n"
            "This is a **research alert only**. No entry/exit instructions. No execution.\n\n"
            "Suggested research checks:\n"
            "- Is this behavior regime-specific or persistent across regimes?\n"
            "- Does microstructure context support or contradict the move?\n"
            "- Does this look stable out-of-sample or likely noise?\n\n"
            "Machine-readable metrics:\n"
            "```json\n"
            f"{json.dumps(self.metrics, indent=2)}\n"
            "```\n"
        )


def _get_json(url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    response = requests.get(url, params=params, timeout=20)
    response.raise_for_status()
    return response.json()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _spread_bps(best_bid: float, best_ask: float) -> float:
    mid = (best_bid + best_ask) / 2
    if mid <= 0:
        return 0.0
    return ((best_ask - best_bid) / mid) * 10000


def evaluate_binance(symbol: str) -> Optional[Alert]:
    ticker = _get_json(f"{BINANCE_FAPI}/fapi/v1/ticker/24hr", params={"symbol": symbol})
    premium = _get_json(f"{BINANCE_FAPI}/fapi/v1/premiumIndex", params={"symbol": symbol})
    open_interest = _get_json(f"{BINANCE_FAPI}/fapi/v1/openInterest", params={"symbol": symbol})
    depth = _get_json(f"{BINANCE_FAPI}/fapi/v1/depth", params={"symbol": symbol, "limit": 20})

    last_price = _safe_float(ticker.get("lastPrice"))
    high_price = _safe_float(ticker.get("highPrice"))
    low_price = _safe_float(ticker.get("lowPrice"))
    price_change_pct = _safe_float(ticker.get("priceChangePercent"))
    funding_rate = _safe_float(premium.get("lastFundingRate"))
    mark_price = _safe_float(premium.get("markPrice"))

    bid = _safe_float(depth.get("bids", [[0]])[0][0]) if depth.get("bids") else 0.0
    ask = _safe_float(depth.get("asks", [[0]])[0][0]) if depth.get("asks") else 0.0

    day_range_pct = ((high_price - low_price) / max(last_price, 1e-9)) * 100
    spread_bps = _spread_bps(bid, ask)

    reasons: List[str] = []
    if abs(price_change_pct) >= PRICE_MOVE_THRESHOLD_PCT:
        reasons.append(f"24h move {price_change_pct:.2f}%")
    if day_range_pct >= RANGE_THRESHOLD_PCT:
        reasons.append(f"24h range {day_range_pct:.2f}%")
    if abs(funding_rate) >= FUNDING_ABS_THRESHOLD:
        reasons.append(f"funding {funding_rate:.5f}")
    if spread_bps >= SPREAD_THRESHOLD_BPS:
        reasons.append(f"spread widening {spread_bps:.2f} bps")

    if not reasons:
        return None

    metrics = {
        "exchange": "BINANCE",
        "symbol": symbol,
        "last_price": last_price,
        "mark_price": mark_price,
        "price_change_pct": round(price_change_pct, 4),
        "day_range_pct": round(day_range_pct, 4),
        "funding_rate": funding_rate,
        "open_interest": _safe_float(open_interest.get("openInterest")),
        "best_bid": bid,
        "best_ask": ask,
        "spread_bps": round(spread_bps, 3),
        "observed_utc": datetime.now(timezone.utc).isoformat(),
    }
    return Alert(exchange="BINANCE", symbol=symbol, reasons=reasons, metrics=metrics)


def evaluate_gate(contract: str) -> Optional[Alert]:
    tickers = _get_json(f"{GATE_REST}/futures/usdt/tickers")
    ticker = next((t for t in tickers if t.get("contract") == contract), None)
    if not ticker:
        return None

    contract_meta = _get_json(f"{GATE_REST}/futures/usdt/contracts/{contract}")
    book = _get_json(f"{GATE_REST}/futures/usdt/order_book", params={"contract": contract, "limit": 20})

    last_price = _safe_float(ticker.get("last"))
    mark_price = _safe_float(ticker.get("mark_price"))
    change_pct = _safe_float(ticker.get("change_percentage"))
    high_24h = _safe_float(ticker.get("high_24h"))
    low_24h = _safe_float(ticker.get("low_24h"))
    funding_rate = _safe_float(contract_meta.get("funding_rate"))

    bid = _safe_float(book.get("bids", [[0]])[0][0]) if book.get("bids") else 0.0
    ask = _safe_float(book.get("asks", [[0]])[0][0]) if book.get("asks") else 0.0

    day_range_pct = ((high_24h - low_24h) / max(last_price, 1e-9)) * 100
    spread_bps = _spread_bps(bid, ask)

    reasons: List[str] = []
    if abs(change_pct) >= PRICE_MOVE_THRESHOLD_PCT:
        reasons.append(f"24h move {change_pct:.2f}%")
    if day_range_pct >= RANGE_THRESHOLD_PCT:
        reasons.append(f"24h range {day_range_pct:.2f}%")
    if abs(funding_rate) >= FUNDING_ABS_THRESHOLD:
        reasons.append(f"funding {funding_rate:.5f}")
    if spread_bps >= SPREAD_THRESHOLD_BPS:
        reasons.append(f"spread widening {spread_bps:.2f} bps")

    if not reasons:
        return None

    metrics = {
        "exchange": "GATE",
        "symbol": contract,
        "last_price": last_price,
        "mark_price": mark_price,
        "price_change_pct": round(change_pct, 4),
        "day_range_pct": round(day_range_pct, 4),
        "funding_rate": funding_rate,
        "funding_interval": contract_meta.get("funding_interval"),
        "funding_next_apply": contract_meta.get("funding_next_apply"),
        "best_bid": bid,
        "best_ask": ask,
        "spread_bps": round(spread_bps, 3),
        "observed_utc": datetime.now(timezone.utc).isoformat(),
    }
    return Alert(exchange="GATE", symbol=contract, reasons=reasons, metrics=metrics)


def gh_headers() -> Dict[str, str]:
    token = os.environ["GITHUB_TOKEN"]
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def repo_parts() -> Tuple[str, str]:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" not in repo:
        raise RuntimeError("GITHUB_REPOSITORY must be in owner/repo form")
    owner, name = repo.split("/", 1)
    return owner, name


def ensure_label(owner: str, repo: str) -> None:
    url = f"{GITHUB_API}/repos/{owner}/{repo}/labels/{ALERT_LABEL}"
    response = requests.get(url, headers=gh_headers(), timeout=20)
    if response.status_code == 200:
        return
    if response.status_code != 404:
        response.raise_for_status()

    create_url = f"{GITHUB_API}/repos/{owner}/{repo}/labels"
    payload = {
        "name": ALERT_LABEL,
        "color": "1d76db",
        "description": "Research-only market watcher alerts",
    }
    create_response = requests.post(create_url, headers=gh_headers(), json=payload, timeout=20)
    if create_response.status_code not in (201, 422):
        create_response.raise_for_status()


def list_open_issues(owner: str, repo: str) -> List[Dict[str, Any]]:
    url = f"{GITHUB_API}/repos/{owner}/{repo}/issues"
    params = {"state": "open", "labels": ALERT_LABEL, "per_page": 100}
    response = requests.get(url, headers=gh_headers(), params=params, timeout=20)
    response.raise_for_status()
    return response.json()


def find_issue(issues: List[Dict[str, Any]], title: str) -> Optional[Dict[str, Any]]:
    for issue in issues:
        if issue.get("title") == title:
            return issue
    return None


def create_issue(owner: str, repo: str, alert: Alert) -> None:
    url = f"{GITHUB_API}/repos/{owner}/{repo}/issues"
    payload = {"title": alert.title, "body": alert.render_body(), "labels": [ALERT_LABEL]}
    response = requests.post(url, headers=gh_headers(), json=payload, timeout=20)
    response.raise_for_status()


def comment_issue(owner: str, repo: str, number: int, alert: Alert) -> None:
    url = f"{GITHUB_API}/repos/{owner}/{repo}/issues/{number}/comments"
    body = f"New research snapshot:\n\n{alert.render_body()}"
    response = requests.post(url, headers=gh_headers(), json={"body": body}, timeout=20)
    response.raise_for_status()


def write_history(alerts: List[Alert]) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = HISTORY_DIR / f"alerts_{stamp}.json"
    payload = [
        {
            "exchange": a.exchange,
            "symbol": a.symbol,
            "reasons": a.reasons,
            "metrics": a.metrics,
        }
        for a in alerts
    ]
    output_path.write_text(json.dumps(payload, indent=2))
    print(f"[info] wrote history snapshot: {output_path}")


def collect_alerts() -> List[Alert]:
    alerts: List[Alert] = []

    for symbol in BINANCE_SYMBOLS:
        try:
            alert = evaluate_binance(symbol)
            if alert:
                alerts.append(alert)
        except Exception as exc:
            print(f"[warn] binance evaluation failed for {symbol}: {exc}", file=sys.stderr)

    for contract in GATE_CONTRACTS:
        try:
            alert = evaluate_gate(contract)
            if alert:
                alerts.append(alert)
        except Exception as exc:
            print(f"[warn] gate evaluation failed for {contract}: {exc}", file=sys.stderr)

    return alerts


def run() -> int:
    alerts = collect_alerts()
    write_history(alerts)

    if not alerts:
        print("[info] no alerts triggered this run")
        return 0

    owner, repo = repo_parts()
    ensure_label(owner, repo)
    open_issues = list_open_issues(owner, repo)

    for alert in alerts:
        issue = find_issue(open_issues, alert.title)
        if issue:
            comment_issue(owner, repo, issue["number"], alert)
            print(f"[info] commented on issue for {alert.exchange}:{alert.symbol}")
        else:
            create_issue(owner, repo, alert)
            print(f"[info] created issue for {alert.exchange}:{alert.symbol}")

    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
