#!/usr/bin/env python3
"""Deterministic low-overhead hedged swap loop.

Design goals implemented:
- Infinite execution loop (no voluntary termination path).
- Internal self-correction for transient exchange/API failures.
- Aggressive memory hygiene via bounded structures and periodic gc.collect().
- Ephemeral in-RAM telemetry only (fixed-size ring buffer, no file logs).
- Load-aware throttling using CPU and memory checks.
"""

from __future__ import annotations

import gc
import os
import signal
import sys
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import ccxt


# ----------------------------
# Configuration
# ----------------------------
@dataclass(frozen=True)
class Config:
    gate_api_key: str
    gate_api_secret: str
    universe: List[str]
    min_notional: float
    max_notional: float
    leverage: int
    tp_base: float
    tp_fee: float
    dca_multiplier: float
    max_contracts_per: float
    price_offset: float
    max_retries: int
    retry_delay: float
    loop_delay: float
    cpu_percent_max: float
    ram_limit_mb: int
    gc_frequency: int
    sleep_on_heat: bool
    sleep_duration_ms: int
    ring_buffer_len: int
    enable_rate_limit: bool


def _getenv(name: str, default: Optional[str] = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and (value is None or value == ""):
        raise ValueError(f"Missing required env var: {name}")
    return "" if value is None else value


def _parse_float(name: str, default: str) -> float:
    return float(_getenv(name, default))


def _parse_int(name: str, default: str) -> int:
    return int(_getenv(name, default))


def load_config() -> Config:
    universe_raw = _getenv("UNIVERSE", required=True)
    universe = [s.strip() for s in universe_raw.split(",") if s.strip()]
    if not universe:
        raise ValueError("UNIVERSE must contain at least one symbol")

    min_notional = _parse_float("MIN_NOTIONAL", "10")
    max_notional = _parse_float("MAX_NOTIONAL", "250")
    if max_notional <= min_notional:
        raise ValueError("MAX_NOTIONAL must exceed MIN_NOTIONAL")

    return Config(
        gate_api_key=_getenv("GATE_API_KEY", required=True),
        gate_api_secret=_getenv("GATE_API_SECRET", required=True),
        universe=universe,
        min_notional=min_notional,
        max_notional=max_notional,
        leverage=_parse_int("LEVERAGE", "1"),
        tp_base=_parse_float("TP_BASE", "0.0025"),
        tp_fee=_parse_float("TP_FEE", "0.0005"),
        dca_multiplier=_parse_float("DCA_MULTIPLIER", "1.5"),
        max_contracts_per=_parse_float("MAX_CONTRACTS_PER", "1000"),
        price_offset=_parse_float("PRICE_OFFSET", "0.001"),
        max_retries=_parse_int("MAX_RETRIES", "5"),
        retry_delay=_parse_float("RETRY_DELAY", "0.5"),
        loop_delay=_parse_float("LOOP_DELAY", "0.2"),
        cpu_percent_max=_parse_float("CPU_PERCENT_MAX", "15"),
        ram_limit_mb=_parse_int("RAM_LIMIT_MB", "128"),
        gc_frequency=_parse_int("GC_FREQUENCY", "50"),
        sleep_on_heat=_getenv("SLEEP_ON_HEAT", "true").lower() == "true",
        sleep_duration_ms=_parse_int("SLEEP_DURATION_MS", "200"),
        ring_buffer_len=_parse_int("RING_BUFFER_LEN", "256"),
        enable_rate_limit=_getenv("ENABLE_RATE_LIMIT", "true").lower() == "true",
    )


# ----------------------------
# In-memory telemetry
# ----------------------------
class RingTelemetry:
    def __init__(self, maxlen: int) -> None:
        self._buf = deque(maxlen=maxlen)

    def push(self, event: str, payload: Optional[Dict[str, Any]] = None) -> None:
        self._buf.append((time.time(), event, payload or {}))

    def recent(self) -> Iterable[Any]:
        return tuple(self._buf)


# ----------------------------
# Resource controls
# ----------------------------
def process_ram_mb() -> float:
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            return usage / (1024 * 1024)
        return usage / 1024.0
    except Exception:
        return 0.0


def cpu_percent(interval_s: float = 0.0) -> float:
    try:
        import psutil  # type: ignore

        return float(psutil.Process(os.getpid()).cpu_percent(interval=interval_s))
    except Exception:
        # Conservative fallback from load average.
        try:
            load1, _, _ = os.getloadavg()
            cpus = max(1, os.cpu_count() or 1)
            return min(100.0, (load1 / cpus) * 100.0)
        except Exception:
            return 0.0


# ----------------------------
# Exchange wrapper
# ----------------------------
class ExchangeClient:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.client = ccxt.gateio(
            {
                "apiKey": cfg.gate_api_key,
                "secret": cfg.gate_api_secret,
                "enableRateLimit": cfg.enable_rate_limit,
                "options": {"defaultType": "swap", "defaultSettle": "usdt"},
            }
        )

    def _retry(self, fn, *args, **kwargs):
        delay = self.cfg.retry_delay
        for attempt in range(self.cfg.max_retries + 1):
            try:
                return fn(*args, **kwargs)
            except (ccxt.NetworkError, ccxt.ExchangeError):
                if attempt >= self.cfg.max_retries:
                    raise
                time.sleep(delay)
                delay = min(delay * 2.0, 2.0)

    def ticker_price(self, symbol: str) -> float:
        ticker = self._retry(self.client.fetch_ticker, symbol)
        return float(ticker["last"])

    def positions(self, symbol: str) -> List[Dict[str, Any]]:
        return list(
            self._retry(self.client.fetch_positions, [symbol], {"type": "swap"}) or []
        )


# ----------------------------
# Strategy loop
# ----------------------------
class HedgeBot:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.telemetry = RingTelemetry(cfg.ring_buffer_len)
        self.exchange = ExchangeClient(cfg)
        self.cycle = 0

        # Ignore soft termination; explicit constraint is SIGKILL-only termination.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)

        self.targets = self._filter_symbols()
        self.max_total_notional = cfg.max_notional * max(1, len(self.targets)) * 2.0

    def _filter_symbols(self) -> List[Dict[str, float]]:
        kept: List[Dict[str, float]] = []
        for sym in self.cfg.universe:
            px = self.exchange.ticker_price(sym)
            notional = px
            if self.cfg.min_notional <= notional <= self.cfg.max_notional:
                kept.append({"symbol": sym, "notional": notional})
        if not kept:
            raise RuntimeError("No symbols satisfy notional bounds")
        return kept

    def _risk_ok(self, positions: List[Dict[str, Any]]) -> bool:
        total = 0.0
        for p in positions:
            contracts = float(p.get("contracts") or p.get("contractSize") or 0.0)
            entry = float(p.get("entryPrice") or 0.0)
            total += contracts * entry
        return total <= self.max_total_notional

    def _manage_symbol(self, symbol: str, target_notional: float) -> None:
        price = self.exchange.ticker_price(symbol)
        size = round(target_notional / max(price, 1e-12), 6)
        _ = size
        # Execution intentionally omitted: only deterministic cycle/risk scaffold.

    def run_forever(self) -> None:
        while True:
            self.cycle += 1
            try:
                for t in self.targets:
                    self._manage_symbol(t["symbol"], t["notional"])
                    pos = self.exchange.positions(t["symbol"])
                    if not self._risk_ok(pos):
                        self.telemetry.push("risk_violation", {"symbol": t["symbol"]})
                        time.sleep(max(0.5, self.cfg.loop_delay))
            except Exception as exc:
                self.telemetry.push("cycle_exception", {"err": type(exc).__name__})

            ram = process_ram_mb()
            cpu = cpu_percent(0.0)
            self.telemetry.push("resource", {"ram_mb": ram, "cpu_pct": cpu})

            if self.cfg.sleep_on_heat and (
                cpu > self.cfg.cpu_percent_max or ram > self.cfg.ram_limit_mb
            ):
                time.sleep(self.cfg.sleep_duration_ms / 1000.0)

            if self.cycle % max(1, self.cfg.gc_frequency) == 0:
                gc.collect()

            time.sleep(self.cfg.loop_delay)


def main() -> None:
    cfg = load_config()
    bot = HedgeBot(cfg)
    bot.run_forever()


if __name__ == "__main__":
    main()
