# Live Alpha Signals (Informational Only)

- Updates every **3 minutes** for **23h/day** via deterministic GitHub Actions (`*/3 0-22 * * *`).
- Mines cross-venue price edges on EVM (UniswapV2-style) and stubs Solana feeds.
- Produces static artifacts only: `signals.json`, `SHASUMS256.txt`, `.last_harvest_utc`, `.last_evolve_utc`. **No keys, no signing, no orders.**

## Configure
1. Populate `manifests/evm_univ2.json` (≥2 venues sharing a `symbol`) and `manifests/solana_accounts.json`.
2. Enable Actions on the repo and push `main`.
3. GitHub-hosted runners execute all logic. There is no optional LLM or external prompt input.

## Automation Surface

| Workflow | Cadence | Purpose |
| --- | --- | --- |
| `harvest` | `*/3 0-22 * * *` + on push | run `scripts/harvest_signals.py`, validate JSON, stamp UTC, and hash `signals.json` |
| `evolve` | `7,37 * * * *` | mutate `seeds.json` deterministically and record last evolve time |
| `pages` | on push + post-harvest | publish the static site to GitHub Pages |
| `health` | hourly + post-run | assert artifact presence and hash continuity; opens an issue on failure |

### Artifact Guarantees
- `signals.json` is JSON-validated before commit; failures keep the prior artifact live on Pages.
- `SHASUMS256.txt` holds the SHA256 digest for reproducibility.
- `.last_harvest_utc` and `.last_evolve_utc` capture the UTC timestamps used during CI.
- `seeds.json` is evolved by CI to drive future focus permutations without any prompts.

## Dashboard
- `index.html` reads `signals.json` from the same origin and refreshes every 15s.
- Positive `edge_bps` rows render green; non-positive render red; TTL reflects generator horizon.

## Execution Constraints
- GitHub Pages serves `index.html` and artifacts; there is **no** backend, WebSocket, or runtime beyond static hosting.
- Workflows run within 120s to prevent overlap; `concurrency` and `timeout-minutes` guard rail pile-ups.
- No secrets, approvals, or external control paths exist; all behavior derives from repository code.

## Data
Each row includes `edge_bps` plus provenance fields `buy_venue`, `sell_venue`, and `assumptions.fees_bps/slip_bps/buffer_bps`.
**Disclaimer:** Informational estimates only.
