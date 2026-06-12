#!/usr/bin/env python3
"""LLM_BIN-compatible proxy that fans prompts out to Ollama instances hosted on Replit.

Mimics the `ollama run <model>` CLI used by scripts/prompt_combinator.py:
reads a prompt on stdin and writes the model's response text to stdout.

Set in .env:
    LLM_BIN=scripts/llm_replit_proxy.py
    LLM_REPLIT_ENDPOINTS=https://node-a.username.repl.co,https://node-b.username.repl.co

Each endpoint should be a Repl running `ollama serve` (see
docs/REPLIT_DEPLOYMENT.md). Endpoints are tried in random order so load is
spread across the available Replit nodes; if all are unreachable this exits
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
        sys.stderr.write("usage: llm_replit_proxy.py run <model>\n")
        return 1

    model = sys.argv[2]
    prompt = sys.stdin.read()

    endpoints = [e.strip() for e in os.getenv("LLM_REPLIT_ENDPOINTS", "").split(",") if e.strip()]
    if not endpoints:
        sys.stderr.write("LLM_REPLIT_ENDPOINTS is not set\n")
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

    sys.stderr.write("all LLM_REPLIT_ENDPOINTS were unreachable\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
