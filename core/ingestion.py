import requests
import json
import logging
import os
from typing import List, Dict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ingestion")

def fetch_gate_tickers() -> List[Dict]:
    url = "https://api.gateio.ws/api/v4/futures/usdt/tickers"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Error fetching Gate.io tickers: {e}")
        return []

def fetch_binance_tickers() -> List[Dict]:
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    try:
        # Binance often blocks requests without a user agent or from certain IPs (like cloud regions).
        # Using a dummy user agent can sometimes help, though 451 means unavailable for legal reasons (geoblocking)
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Error fetching Binance tickers: {e}")
        return []

def analyze_gate_data(tickers: List[Dict]) -> List[str]:
    alerts = []
    for ticker in tickers:
        contract = ticker.get('contract', '')
        funding_rate_str = ticker.get('funding_rate', '0')
        try:
            funding_rate = float(funding_rate_str)
            if abs(funding_rate) > 0.001:
                alerts.append(f"- **Gate.io**: Extreme funding rate on `{contract}`: {funding_rate:.6f}")
        except (ValueError, TypeError):
            pass
    return alerts

def analyze_binance_data(tickers: List[Dict]) -> List[str]:
    alerts = []
    for ticker in tickers:
        symbol = ticker.get('symbol', '')
        price_change_percent_str = ticker.get('priceChangePercent', '0')
        try:
            price_change_percent = float(price_change_percent_str)
            if abs(price_change_percent) > 20.0:  # Bumped to 20% to reduce noise
                alerts.append(f"- **Binance**: Volatility spike on `{symbol}`: {price_change_percent:.2f}% 24h change")
        except (ValueError, TypeError):
            pass
    return alerts

def run_ingestion():
    logger.info("Starting ingestion...")
    gate_tickers = fetch_gate_tickers()
    binance_tickers = fetch_binance_tickers()

    alerts = []
    alerts.extend(analyze_gate_data(gate_tickers))
    alerts.extend(analyze_binance_data(binance_tickers))

    if not alerts:
        output = "No significant research alerts found."
    else:
        output_lines = ["# Market Research Alerts\n"]
        output_lines.extend(alerts[:20])
        if len(alerts) > 20:
            output_lines.append(f"\n...and {len(alerts) - 20} more alerts.")
        output = "\n".join(output_lines)

    print(output)

    # If running in GitHub Actions, we might want to write to a file or set an output
    with open("alerts.md", "w") as f:
        f.write(output)

if __name__ == "__main__":
    run_ingestion()
