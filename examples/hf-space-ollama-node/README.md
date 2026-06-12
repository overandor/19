---
title: Ollama Inference Node
emoji: 🦙
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 11434
---

# Ollama inference node

A minimal Ollama server, intended as one node in a `LLM_DISTRIBUTED_ENDPOINTS`
pool (see `docs/DISTRIBUTED_LLM_INFERENCE.md` in the
[main repo](https://github.com/overandor/19)).

On startup the container runs `ollama serve` and pulls the model named by the
`OLLAMA_MODEL` Space variable (default `codellama:7b`). Once the Space is
running, its base URL (`https://<your-username>-<space-name>.hf.space`) can
be added to `LLM_DISTRIBUTED_ENDPOINTS`.

This node has no authentication — anyone with the URL can send it prompts.
Don't point it at anything beyond the research-only focus ranker in this
repo, and be mindful of Hugging Face's usage policies for the hardware tier
you choose.
