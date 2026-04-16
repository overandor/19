#!/usr/bin/env python3
"""Research-only perpetual futures alert watcher.

This script fetches public market data and opens/comments GitHub issues with
research alerts. It never generates executable trade instructions.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

GITHUB_API = "https://api.github.com"
BINANCE_FAPI = "https://fapi.binance.com"

# Research-only thresholds.
VOLATILITY_THRESHOLD_PCT = 1.5
PRICE_MOVE_THRESHOLD_PCT = 1.0
FUNDING_ABS_THRESHOLD = 0.0005

ALERT_LABEL = "research-alert"
ISSUE_TITLE_PREFIX = "Research alert:"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


@dataclass
class Alert:
    symbol: str
    reason: str
    metrics: Dict[str, Any]
    body: str


def get_json(url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    response = requests.get(url, params=params, timeout=20)
    response.raise_for_status()
    return response.json()


def fetch_binance_24h(symbol: str) -> Dict[str, Any]:
    return get_json(f"{BINANCE_FAPI}/fapi/v1/ticker/24hr", params={"symbol": symbol})


def fetch_binance_mark_price(symbol: str) -> Dict[str, Any]:
    return get_json(f"{BINANCE_FAPI}/fapi/v1/premiumIndex", params={"symbol": symbol})


def build_alert_body(symbol: str, reason: str, metrics: Dict[str, Any]) -> str:
    return (
        f"Research alert for `{symbol}`.\n\n"
        f"Reason:\n- {reason}\n\n"
        f"Metrics:\n"
        f"- Last price: `{metrics['last_price']}`\n"
        f"- Mark price: `{metrics['mark_price']}`\n"
        f"- 24h move: `{metrics['price_change_pct']:.2f}%`\n"
        f"- 24h range proxy: `{metrics['day_range_pct']:.2f}%`\n"
        f"- Funding rate: `{metrics['funding_rate']:.5f}`\n\n"
        "Interpretation:\n"
        "This is a **research alert only**. Review manually. No execution.\n\n"
        "Suggested review questions:\n"
        "- Is this trend continuation, squeeze risk, or mean-reversion context?\n"
        "- Is funding aligned or stretched versus recent history?\n"
        "- Should this be added to a paper-research watchlist?\n\n"
        "Machine-readable metrics:\n"
        "```json\n"
        f"{json.dumps(metrics, indent=2)}\n"
        "```\n"
    )


def evaluate_symbol(symbol: str) -> Optional[Alert]:
    ticker = fetch_binance_24h(symbol)
    premium = fetch_binance_mark_price(symbol)

    last_price = float(ticker["lastPrice"])
    high_price = float(ticker["highPrice"])
    low_price = float(ticker["lowPrice"])
    price_change_pct = float(ticker["priceChangePercent"])
    funding_rate = float(premium["lastFundingRate"])
    mark_price = float(premium["markPrice"])

    day_range_pct = ((high_price - low_price) / max(last_price, 1e-9)) * 100.0
    move_pct = abs(price_change_pct)

    reasons: List[str] = []
    if move_pct >= PRICE_MOVE_THRESHOLD_PCT:
        reasons.append(f"24h move {price_change_pct:.2f}%")
    if day_range_pct >= VOLATILITY_THRESHOLD_PCT:
        reasons.append(f"24h range {day_range_pct:.2f}%")
    if abs(funding_rate) >= FUNDING_ABS_THRESHOLD:
        reasons.append(f"funding {funding_rate:.5f}")

    if not reasons:
        return None

    metrics = {
        "last_price": last_price,
        "mark_price": mark_price,
        "price_change_pct": round(price_change_pct, 4),
        "day_range_pct": round(day_range_pct, 4),
        "funding_rate": funding_rate,
        "volume": ticker.get("volume"),
        "quote_volume": ticker.get("quoteVolume"),
        "observed_utc": datetime.now(timezone.utc).isoformat(),
    }
    reason = "; ".join(reasons)
    body = build_alert_body(symbol, reason, metrics)
    return Alert(symbol=symbol, reason=reason, metrics=metrics, body=body)


def gh_headers() -> Dict[str, str]:
    token = os.environ["GITHUB_TOKEN"]
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_repo_parts() -> Tuple[str, str]:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" not in repo:
        raise RuntimeError("GITHUB_REPOSITORY must be in owner/repo form")
    return tuple(repo.split("/", 1))  # type: ignore[return-value]


def create_label_if_missing(owner: str, repo: str, dry_run: bool = False) -> None:
    url = f"{GITHUB_API}/repos/{owner}/{repo}/labels/{ALERT_LABEL}"
    response = requests.get(url, headers=gh_headers(), timeout=20)
    if response.status_code == 200:
        return
    if response.status_code != 404:
        response.raise_for_status()

    if dry_run:
        print(f"[dry-run] would create label {ALERT_LABEL}")
        return

    create_url = f"{GITHUB_API}/repos/{owner}/{repo}/labels"
    payload = {
        "name": ALERT_LABEL,
        "color": "1d76db",
        "description": "Research-only market watch alerts",
    }
    create_response = requests.post(create_url, headers=gh_headers(), json=payload, timeout=20)
    if create_response.status_code not in (201, 422):
        create_response.raise_for_status()


def list_open_alert_issues(owner: str, repo: str) -> List[Dict[str, Any]]:
    url = f"{GITHUB_API}/repos/{owner}/{repo}/issues"
    params = {"state": "open", "labels": ALERT_LABEL, "per_page": 100}
    response = requests.get(url, headers=gh_headers(), params=params, timeout=20)
    response.raise_for_status()
    return response.json()


def find_issue_for_symbol(issues: List[Dict[str, Any]], symbol: str) -> Optional[Dict[str, Any]]:
    expected = f"{ISSUE_TITLE_PREFIX} {symbol}"
    for issue in issues:
        if issue.get("title") == expected:
            return issue
    return None


def create_issue(owner: str, repo: str, title: str, body: str, dry_run: bool = False) -> None:
    if dry_run:
        print(f"[dry-run] would create issue: {title}")
        return
    url = f"{GITHUB_API}/repos/{owner}/{repo}/issues"
    payload = {"title": title, "body": body, "labels": [ALERT_LABEL]}
    response = requests.post(url, headers=gh_headers(), json=payload, timeout=20)
    response.raise_for_status()


def comment_issue(owner: str, repo: str, issue_number: int, body: str, dry_run: bool = False) -> None:
    if dry_run:
        print(f"[dry-run] would comment on issue #{issue_number}")
        return
    url = f"{GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}/comments"
    response = requests.post(url, headers=gh_headers(), json={"body": body}, timeout=20)
    response.raise_for_status()


def run(dry_run: bool = False) -> int:
    owner, repo = get_repo_parts()
    create_label_if_missing(owner, repo, dry_run=dry_run)

    open_issues = list_open_alert_issues(owner, repo)
    any_alerts = False

    for symbol in SYMBOLS:
        try:
            alert = evaluate_symbol(symbol)
        except Exception as exc:
            print(f"[warn] failed to evaluate {symbol}: {exc}", file=sys.stderr)
            continue

        if alert is None:
            print(f"[info] no research alert for {symbol}")
            continue

        any_alerts = True
        title = f"{ISSUE_TITLE_PREFIX} {symbol}"
        existing = find_issue_for_symbol(open_issues, symbol)
        if existing:
            comment_issue(
                owner,
                repo,
                existing["number"],
                f"New research alert snapshot:\n\n{alert.body}",
                dry_run=dry_run,
            )
            print(f"[info] updated existing issue for {symbol}")
        else:
            create_issue(owner, repo, title, alert.body, dry_run=dry_run)
            print(f"[info] created new issue for {symbol}")

    if not any_alerts:
        print("[info] no alerts triggered this run")

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research-only perpetual futures alerts")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate and log actions without creating/updating issues")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
