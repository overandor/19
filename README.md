# Autonomous Alpha Console

Deterministic, neomorphic telemetry surface streaming cross-venue spreads with live WebSocket control, scheduled harvesting, and containerized deployment.

## Runtime surfaces
- `backend.py` — FastAPI bridge exposing `/ws`, `/scan`, `/focus`, `/signals`. Threads generate scans without blocking event loop.
- `index.html` — Neomorphic console pulling `signals.json`, orchestrating WebSocket actions, and rendering gross/net edge columns.
- `scripts/` — deterministic analytics stack (`prompt_combinator.py`, `harvest_signals.py`, `evm_univ2.py`, `edge_math.py`, `solana_stub.py`).
- `cache/focus.json`, `signals.json` — persisted artifacts committed by CI for GitHub Pages and WebSocket fallbacks.

## Manifests (no placeholders)
- `manifests/evm_univ2.json` — uses `https://eth.llamarpc.com` plus the canonical Uniswap V2 and SushiSwap USDC/WETH pools.
- `manifests/solana_accounts.json` — hits `https://api.mainnet-beta.solana.com` with real Pyth SOL/USD price account and Raydium SOL/USDC AMM state.
- `manifests/perps_hedge.json` — deterministic hedge assumptions (notional, perp fees, funding, borrow APR, hold horizon) plus `max_network_fee_usd` threshold for eligible perp routing.
- `manifests/perps_venues.json` — curated perp venue set (10 exchanges) across Solana/Base/Arbitrum/BSC/Hyperliquid with deterministic `estimated_network_fee_usd`.

## CI / automation
`.github/workflows/harvest.yml`
- schedule: `*/3 0-22 * * *` (23h/day) + manual dispatch.
- steps: install, `python -m compileall`, focus recompute (LLM optional), signal harvest, conditional `docker build` on non-scheduled triggers, commit `signals.json` + `cache/focus.json`.
- artifact shape: signals include `edge_bps_gross` and `edge_bps` (net after fees/slippage/buffer).

## Docker
### Build + run directly
```bash
docker build -t alpha-console .
docker run --rm -p 8765:8765 alpha-console
```
### Compose (backend + static dashboard)
```bash
docker compose up --build
# backend: 0.0.0.0:8765 (FastAPI)
# dashboard: http://localhost:8080/index.html
```
Caddy serves the static assets while the Python container exposes `/ws` and REST fallbacks.

## Local workflow
```bash
python -m pip install -r requirements.txt
python -m scripts.prompt_combinator
python -m scripts.harvest_signals
python backend.py  # serves ws://0.0.0.0:8765/ws
python -m http.server 8080  # optional static hosting for index.html
```
Open `http://localhost:8080/index.html` and connect. The console targets `http://<host>:8765` for API/WebSocket by default; override via `?api=` (REST) and `?ws=` (WebSocket) or the control panel input.
Open `http://localhost:8080/index.html` and connect (defaults to `ws://localhost:8765/ws`; override via `?ws=` or the control panel).

## Signal schema
```json
{
  "chain": "EVM",
  "symbol": "WETH/USDC",
  "best_bid": 3438.2260,
  "best_ask": 3435.2318,
  "sell_venue": "UNISWAP_V2",
  "buy_venue": "SUSHISWAP",
  "edge_bps_gross": 8.71,
  "edge_bps": -26.28,
  "ttl_seconds": 30,
  "ts": 1762587233,
  "assumptions": {
    "fees_bps": 30,
    "slip_bps": 3,
    "buffer_bps": 2
  },
  "perps_hedge": {
    "config": {
      "spot_notional_usd": 10000,
      "perp_taker_bps_roundtrip": 8,
      "funding_rate_bps_8h": 1.2,
      "borrow_apr_bps": 450,
      "expected_hold_hours": 2,
      "max_network_fee_usd": 0.10,
      "preferred_networks": ["base", "solana", "arbitrum", "hyperliquid", "bsc"],
      "min_venues": 4,
      "max_venues": 14
    },
    "eligible_venues": [
      {"venue": "DRIFT", "network": "solana", "estimated_network_fee_usd": 0.002},
      {"venue": "ZETA", "network": "solana", "estimated_network_fee_usd": 0.002},
      {"venue": "MANGO", "network": "solana", "estimated_network_fee_usd": 0.003},
      {"venue": "SYNTHETIX_PERPS", "network": "base", "estimated_network_fee_usd": 0.020},
      {"venue": "KWENTA_PERPS", "network": "base", "estimated_network_fee_usd": 0.020},
      {"venue": "BASEDAPP_PERPS", "network": "base", "estimated_network_fee_usd": 0.020},
      {"venue": "GMX_PERPS", "network": "arbitrum", "estimated_network_fee_usd": 0.080},
      {"venue": "VERTEX_PERPS", "network": "arbitrum", "estimated_network_fee_usd": 0.080},
      {"venue": "HYPERLIQUID_PERPS", "network": "hyperliquid", "estimated_network_fee_usd": 0.000},
      {"venue": "LEVEL_PERPS", "network": "bsc", "estimated_network_fee_usd": 0.050}
    ],
    "eligible_venues_meta": {
      "selected_count": 10,
      "required_min_count": 4,
      "is_min_satisfied": true
    },
    "result": {
      "spot_notional_usd": 10000.0,
      "base_units": 2.9109,
      "gross_spread_usd": 8.72,
      "costs_usd": {
        "spot_execution": 35.0,
        "perp_execution": 8.0,
        "funding": 3.0,
        "borrow": 0.10,
        "total": 46.10
      },
      "net_hedged_pnl_usd": -37.38,
      "net_hedged_edge_bps": -37.38,
      "break_even_hold_hours": -17.45
    }
  }
}
```
Gross column is the raw bid/ask spread; net column subtracts fees, slip, and buffer. `perps_hedge.result.net_hedged_edge_bps` adds carry-adjusted economics for DEX spot + perp hedge routing, while `perps_hedge.eligible_venues` constrains perp venues to `estimated_network_fee_usd <= max_network_fee_usd` (default $0.10).

## Perp venue attachment policy
- Selection objective: expose deterministic hedgeable perp routes with strict low-fee admission and bounded fan-out.
- Admission constraint: include venue iff `estimated_network_fee_usd <= max_network_fee_usd` from hedge config.
- Cardinality constraints: clamp to `[4, 14]` venues using `min_venues`/`max_venues`; emit runtime satisfaction flag in payload.
- Ordering constraints (stable): `preferred_networks` rank, then `estimated_network_fee_usd`, then lexical `venue` for deterministic replay.
- Payload fields:
  - `perps_hedge.config` includes venue policy inputs (`max_network_fee_usd`, `preferred_networks`, `min_venues`, `max_venues`).
  - `perps_hedge.eligible_venues` contains selected venue rows for execution planner input.
  - `perps_hedge.eligible_venues_meta` publishes `selected_count`, `required_min_count`, `is_min_satisfied` for guardrail checks.

## Health
- `GET /health` — liveness probe.
- `GET /signals` — synchronous harvest without persistence.
- `POST /scan {"persist": true}` — re-run harvest and update `signals.json`.
- `POST /focus` — recompute entropy-ranked targets (writes `cache/focus.json`).
- WebSocket `/ws` — accepts `{ "type": "scan"|"focus", "persist": bool }` messages and returns structured payloads.

## Deployment notes
- No private keys, dispatchers, or execution stubs shipped.
- LLM ranking is optional; when `ollama` is absent CI logs the fallback path and proceeds deterministically.
- Docker images stay <200 MB and install no GPU tooling; safe for CPU-only hosts.
