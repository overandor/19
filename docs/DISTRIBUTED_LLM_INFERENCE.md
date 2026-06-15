# Distributed LLM Inference (Replit + Hugging Face Spaces)

This guide covers two independent things:

1. **The research API** (`backend.py`) — the FastAPI service behind `/signals`,
   `/focus`, and `/scan`. Hosting it on Replit is covered in
   [§1](#1-hosting-the-backend-api).
2. **A pool of remote Ollama nodes** for the optional focus ranker used by
   `scripts/prompt_combinator.py` (`llm_rank` / `compute_focus`), hosted on
   free platforms like Replit and Hugging Face Spaces. Covered in
   [§2](#2-a-distributed-ollama-node-pool).

Both are config-only additions — `scripts/prompt_combinator.py`'s core
inference call is unchanged: it still just runs `LLM_BIN run LLM_MODEL` and
reads the result from stdout. The pieces below are just more places that
binary can point at.

## 1. Hosting the backend API

The root `.replit` file configures a Repl that installs `requirements.txt`
and runs `uvicorn backend:app`:

```toml
modules = ["python-3.11"]
run = "uvicorn backend:app --host 0.0.0.0 --port 8765"

[deployment]
deploymentTarget = "vm"
run = ["sh", "-c", "uvicorn backend:app --host 0.0.0.0 --port 8765"]
build = ["sh", "-c", "pip install -r requirements.txt"]
```

Steps:

1. Import this repository into a new Repl (or `git pull` into an existing one).
2. Add secrets via the Replit "Secrets" pane for anything in `.env.example`
   you want to override (`API_KEY`, `CORS_ORIGINS`, `LOG_FORMAT`, etc.).
   Never commit real secrets to `.env`.
3. Use Replit's **Deployments** tab with the "Reserved VM" target so the
   process stays warm — the focus/scan endpoints do real work and shouldn't
   cold-start on every request.
4. Point the static dashboard's `BACKEND_URL` (see `index.html` /
   `vercel.json`) at the Repl's deployment URL.

The `/health` endpoint is suitable for Replit's deployment health checks.

## 2. A distributed Ollama node pool

`compute_focus()` calls `llm_rank()`, which shells out to:

```
LLM_BIN run LLM_MODEL   # default: ollama run codellama:13b
```

and falls back to a deterministic random shuffle if that command fails or
times out (45s). Nothing about that contract changes here — `LLM_BIN` is
just pointed at `scripts/llm_distributed_proxy.py`, a small script that
speaks the same `run <model>` / stdin-prompt / stdout-response contract as
`ollama run`, but forwards the request over HTTP to one of several
**remote** Ollama nodes:

```bash
LLM_BIN=scripts/llm_distributed_proxy.py
LLM_MODEL=codellama:7b
LLM_DISTRIBUTED_ENDPOINTS=https://node-a.username.repl.co,https://node-b.hf.space
```

Each call picks a node at random, so requests spread across whichever nodes
happen to be awake — a simple peer pool rather than one fixed always-local
host. If every node is unreachable, the proxy exits non-zero and
`prompt_combinator.py`'s existing random-shuffle fallback applies, exactly
as it does today when `ollama` isn't installed locally.

Keep `LLM_MODEL` consistent across nodes — the proxy doesn't negotiate
per-node model availability.

### 2a. Replit node

1. Create a Repl from the [Nix template](https://replit.com/@replit/Nix) (or
   any template with shell access).
2. Add an `.replit` file in that Repl:

   ```toml
   run = "ollama serve"

   [[ports]]
   localPort = 11434
   externalPort = 80
   ```

3. In the Repl shell, install Ollama and pull a model that fits the Repl's
   RAM/CPU budget:

   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ollama pull codellama:7b
   ```

4. Deploy the Repl and note its URL, e.g. `https://my-ollama-node.username.repl.co`.

### 2b. Hugging Face Spaces node

`examples/hf-space-ollama-node/` is a ready-to-copy Docker Space:

- `README.md` carries the HF Space config card (`sdk: docker`,
  `app_port: 11434`).
- `Dockerfile` + `entrypoint.sh` run `ollama serve` and pull `OLLAMA_MODEL`
  (default `codellama:7b`) on startup.

To use it:

1. Create a new Space at <https://huggingface.co/new-space> with the
   **Docker** SDK.
2. Copy the contents of `examples/hf-space-ollama-node/` into the Space repo
   (via the web UI, `git push`, or the Hugging Face Hub MCP tools).
3. Optionally set the `OLLAMA_MODEL` variable in the Space settings to match
   `LLM_MODEL`.
4. Once the Space is running, its endpoint is
   `https://<your-username>-<space-name>.hf.space`.

### 2c. Wire the nodes together

Add each node's URL to `LLM_DISTRIBUTED_ENDPOINTS` (comma-separated) in
`.env`:

```bash
LLM_BIN=scripts/llm_distributed_proxy.py
LLM_MODEL=codellama:7b
LLM_DISTRIBUTED_ENDPOINTS=https://my-ollama-node.username.repl.co,https://my-username-ollama-node.hf.space
```

`_invoke_llm()` in `prompt_combinator.py` is unchanged; it just now runs a
Python script instead of the `ollama` CLI directly.

## "Always on" considerations

Free tiers on both platforms sleep idle apps:

- **Replit**: free/Autoscale Repls sleep when idle; a Reserved VM deployment
  stays on continuously (paid).
- **Hugging Face Spaces**: free CPU Spaces sleep after a period of
  inactivity; "Sleep time" can be disabled on paid hardware tiers, or the
  Space restarts on the next request (with a cold-start delay).

The proxy tolerates a mostly-asleep pool — it just tries the next node and,
if everything is down, the caller falls back to random-shuffle ranking. But
if you want the focus ranker to reliably use an LLM rather than the
fallback, **at least one node in `LLM_DISTRIBUTED_ENDPOINTS` needs to stay
on**: either a Reserved VM Repl, or an HF Space on a tier without sleep. The
proxy's 20s per-node timeout (and the caller's overall 45s timeout) may be
exhausted waking a sleeping node before a response comes back.

## Notes / limits

- This project is **research-only** (see `safety_policies/research_only_policy.md`):
  the focus ranker only reorders which DeFi pairs/venues get scanned next, it
  never places orders.
- `LLM_DISTRIBUTED_ENDPOINTS` is plain HTTP(S) to whatever you deploy; don't
  expose an Ollama node publicly without considering who else can call it (it
  has no built-in auth). Treat each node as a public, unauthenticated
  endpoint and respect Replit's and Hugging Face's terms of service for the
  tier you're using.
