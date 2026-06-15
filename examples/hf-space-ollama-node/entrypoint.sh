#!/bin/sh
set -e

ollama serve &
server_pid=$!

# Wait for the server to come up, then pull the configured model.
until ollama list >/dev/null 2>&1; do
    sleep 1
done
ollama pull "${OLLAMA_MODEL:-codellama:7b}"

wait "$server_pid"
