# memory_shell

A sandboxed shell that cuts an LLM server's resident memory.

- `weights.py` — one `MAP_SHARED` mapping per model file instead of a
  private copy per worker. Measured: 8 workers, 64MiB model, **64.1MiB
  actual RSS instead of 512MiB**.
- `blocks.py` / `store.py` — KV and prefix state named by content hash, so
  identical state costs one copy. Refcounted under a byte budget; a block
  a live session is reading is never evicted.
- `isolation.py` — the reason this is a *secure* shell. A shared prefix
  cache is an oracle answering "has anyone here seen this?" about other
  people's prompts, so state derived from tenant input is private by
  default and identical bytes across tenants are stored twice on purpose.
- `shell.py` — sessions, and the loop back to `proof_of_avoided_work`: a
  miss is a timed cold execution (a baseline sample), a hit is a reuse
  claim with a measured cost.
- `remote.py` — a stdio service for `sshd` to run as a forced command. It
  does not implement SSH; the tenant comes from `authorized_keys`, never
  from the request.

```bash
python -m memory_shell measure   # real RSS measurement of weight sharing
python -m memory_shell demo      # multi-tenant savings and isolation
python -m memory_shell serve     # the stdio service sshd invokes
```

Protocol, `authorized_keys` config, macOS packaging, and an explicit list
of what is *not* done: `docs/MEMORY_SHELL.md`.
