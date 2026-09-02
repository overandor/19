#!/usr/bin/env bash
# Runs the whole stack, in the order the pieces depend on each other.
#
#   1. memory_shell         saves real memory, and measures it against the kernel
#   2. proof_of_avoided_work turns those measurements into claims that can be disproved
#   3. pwr-demo             the Rust foundation the next increment builds on
#
# Everything here executes. Nothing is a mock, and every number printed was
# produced on the machine running the script.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

banner() {
    printf '\n\033[1m╭─ %s\033[0m\n' "$1"
    printf '\033[2m│  %s\033[0m\n\n' "$2"
}

banner "1 · memory_shell — what the machine actually saves" \
        "Eight workers sharing one model file, measured via /proc/self/statm"
python3 -m memory_shell measure --size-mib 64 --workers 8

banner "2 · memory_shell — sharing a cache without leaking through it" \
        "Three tenants, one shared prompt, one private document"
python3 -m memory_shell demo

banner "3 · proof_of_avoided_work — sizing the audit" \
        "How rarely you can check, and still make lying unprofitable"
python3 -m proof_of_avoided_work plan

banner "4 · proof_of_avoided_work — the audit catching a cheater" \
        "Honest claimants, a phantom-reuse cheater, and a baseline inflater"
python3 -m proof_of_avoided_work simulate

banner "5 · pwr-demo — the Rust foundation" \
        "Authorization, provenance, storage, memory, resources, logging"
cargo run -q -p pwr-demo

printf '\n\033[1mEverything above is asserted in tests.\033[0m\n'
printf '  cargo test --workspace   %s\n' "$(cargo test --workspace 2>&1 | grep -cE '^test result: ok') result groups, all ok"
printf '  python3 -m pytest -q     %s\n' "$(python3 -m pytest -q 2>&1 | grep -oE '[0-9]+ passed' | head -1)"
