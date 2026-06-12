# Deploying on Replit

This guide covers two independent things you can host on [Replit](https://replit.com):

1. **The research API** (`backend.py`) — the FastAPI service behind `/signals`,
   `/focus`, and `/scan`.
2. **Distributed LLM inference nodes** for the optional focus ranker used by
   `scripts/prompt_combinator.py` (`llm_rank` / `compute_focus`).

Both are config-only additions — no changes to the core inference call in
`scripts/prompt_combinator.py`, which still just runs `LLM_BIN run LLM_MODEL`
and reads the result from stdout. Replit is one more place that binary can
point at.

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

## 2. Distributed LLM inference for the focus ranker

`compute_focus()` calls `llm_rank()`, which shells out to:

```
LLM_BIN run LLM_MODEL   # default: ollama run codellama:13b
```

and falls back to a deterministic random shuffle if that command fails or
times out (45s). Nothing about that contract changes — we're just adding
new things `LLM_BIN` can point to.

### 2a. One Ollama node per Repl

Run each inference node as its own Repl:

1. Create a Repl from the [Nix template](https://replit.com/@replit/Nix) (or
   any template with shell access).
2. Add an `.replit` file in that Repl:

   ```toml
   run = "ollama serve"

   [[ports]]
   localPort = 11434
   externalPort = 80
   ```

3. In the Repl shell, install Ollama and pull a small model that fits in the
   Repl's RAM/CPU budget, e.g.:

   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ollama pull codellama:7b
   ```

4. Deploy the Repl (Reserved VM recommended — free/Autoscale Repls sleep when
   idle and Ollama's first response after a cold start can exceed the 45s
   timeout). Note the deployment URL, e.g.
   `https://my-ollama-node.username.repl.co`.

Repeat for as many nodes as you want — each is an independent Repl, so this
scales horizontally ("distributed") simply by adding more URLs in step 3
below. Keep `LLM_MODEL` consistent across nodes, since the proxy doesn't
negotiate per-node model availability.

### 2b. Wire the nodes into prompt_combinator.py

`scripts/llm_replit_proxy.py` is a drop-in `LLM_BIN`: it speaks the same
`run <model>` / stdin-prompt / stdout-response contract as `ollama run`, but
forwards the request over HTTP to one of your Replit-hosted Ollama nodes
(picked at random per call, so requests spread across nodes), and exits
non-zero if all nodes are unreachable so the existing random-shuffle fallback
still applies.

In `.env`:

```bash
LLM_BIN=scripts/llm_replit_proxy.py
LLM_MODEL=codellama:7b
LLM_REPLIT_ENDPOINTS=https://node-a.username.repl.co,https://node-b.username.repl.co
```

That's it — `_invoke_llm()` in `prompt_combinator.py` is unchanged; it just
now runs a Python script instead of the `ollama` CLI directly.

## Notes / limits

- This project is **research-only** (see `safety_policies/research_only_policy.md`):
  the focus ranker only reorders which DeFi pairs/venues get scanned next, it
  never places orders.
- Free Replit plans put compute and always-on limits on Repls; if a node is
  asleep when called, the proxy's 20s per-node timeout (and the caller's 45s
  total timeout) may be exhausted before it wakes — add more nodes or use
  Reserved VM deployments for nodes you rely on.
- `LLM_REPLIT_ENDPOINTS` is plain HTTP(S) to whatever you deploy; don't expose
  an Ollama node publicly without considering who else can call it (it has no
  built-in auth).
