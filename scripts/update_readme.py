#!/usr/bin/env python3
import json
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
SIGNALS = ROOT / "signals.json"

START = "<!-- SIGNALS:START -->"
END = "<!-- SIGNALS:END -->"


def load_signals() -> Dict:
    try:
        return json.loads(SIGNALS.read_text())
    except Exception:
        return {"generated_at": 0, "signals": []}


def format_table(signals: List[Dict]) -> str:
    header = (
        "| Symbol | Buy | Sell | Gross bps | Net bps | TTL | Updated |\n"
        "|---|---|---|---:|---:|---:|---|\n"
    )
    rows = []
    for row in signals[:12]:
        rows.append(
            "| {symbol} | {buy} | {sell} | {gross:.2f} | {net:.2f} | {ttl}s | {ts} |".format(
                symbol=row.get("symbol", "-"),
                buy=row.get("buy_venue", "-"),
                sell=row.get("sell_venue", "-"),
                gross=float(row.get("edge_bps_gross", 0)),
                net=float(row.get("edge_bps", 0)),
                ttl=int(row.get("ttl_seconds", 0)),
                ts=int(row.get("ts", 0)),
            )
        )
    if not rows:
        rows.append("| - | - | - | 0.00 | 0.00 | 0s | 0 |")
    return header + "\n".join(rows)


def render_block(payload: Dict) -> str:
    signals = payload.get("signals", []) if isinstance(payload, dict) else []
    generated_at = int(payload.get("generated_at", 0)) if isinstance(payload, dict) else 0
    top_net = max((float(s.get("edge_bps", 0)) for s in signals), default=0.0)
    count = len(signals)
    return (
        f"generated_at_unix: {generated_at}\n"
        f"signal_count: {count}\n"
        f"top_edge_bps: {top_net:.2f}\n\n"
        + format_table(signals)
    )


def update_readme(block: str) -> None:
    content = README.read_text()
    if START not in content or END not in content:
        raise SystemExit("README markers missing")
    before, rest = content.split(START, 1)
    _, after = rest.split(END, 1)
    new = before + START + "\n" + block.rstrip() + "\n" + END + after
    README.write_text(new)


def main() -> None:
    payload = load_signals()
    block = render_block(payload)
    update_readme(block)


if __name__ == "__main__":
    main()
