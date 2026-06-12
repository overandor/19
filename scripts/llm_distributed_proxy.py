#!/usr/bin/env python3
"""LLM_BIN-compatible proxy that fans prompts out to a pool of hosted Ollama nodes.

Mimics the `ollama run <model>` CLI used by scripts/prompt_combinator.py:
reads a prompt on stdin and writes the model's response text to stdout.

Set in .env:
    LLM_BIN=scripts/llm_distributed_proxy.py
    LLM_DISTRIBUTED_ENDPOINTS=https://node-a.username.repl.co,https://node-b.hf.space

Each endpoint is a node running `ollama serve` reachable over HTTP — hosted
on Replit, a Hugging Face Space, or anywhere else (see
docs/DISTRIBUTED_LLM_INFERENCE.md). Endpoints are tried in random order so
load is spread across whichever nodes are awake, giving a simple p2p-style
pool rather than a single fixed host. If all are unreachable this exits
non-zero and prompt_combinator.py falls back to its random-shuffle ranking.
"""
from __future__ import annotations

import os
import random
import sys

import requests

TIMEOUT_SECONDS = 20


def main() -> int:
    if len(sys.argv) < 3 or sys.argv[1] != "run":
        sys.stderr.write("usage: llm_distributed_proxy.py run <model>\n")
        return 1

    model = sys.argv[2]
    prompt = sys.stdin.read()

    endpoints = [e.strip() for e in os.getenv("LLM_DISTRIBUTED_ENDPOINTS", "").split(",") if e.strip()]
    if not endpoints:
        sys.stderr.write("LLM_DISTRIBUTED_ENDPOINTS is not set\n")
        return 1

    random.shuffle(endpoints)
    for endpoint in endpoints:
        try:
            resp = requests.post(
                f"{endpoint.rstrip('/')}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
                timeout=TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            sys.stdout.write(resp.json().get("response", ""))
            return 0
        except (requests.RequestException, ValueError):
            continue

    sys.stderr.write("all LLM_DISTRIBUTED_ENDPOINTS were unreachable\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
