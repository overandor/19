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
  }
}
```
Gross column is the raw bid/ask spread; net column subtracts fees, slip, and buffer.

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
