# memory_shell

A sandboxed shell that cuts an LLM server's resident memory, and does the
sharing without turning the cache into an oracle about other people's
prompts.

## The two mechanisms

**Shared weights.** A 7B model at 16-bit is roughly 14GiB. A server that
loads it once per worker pays that per worker; mapping the file
`MAP_SHARED` pays it once total, because every mapping resolves to the
same page cache pages. Measured on this machine, eight mappings of a 64MiB
file with every page touched:

```
$ python -m memory_shell measure
weights file      : 64.0MiB
workers           : 8
private copies    : 512.0MiB  (what N copies cost)
shared mapping    : 64.0MiB
saved             : 448.0MiB
measured RSS delta: 64.1MiB  (kernel, after touching every page)

RSS tracks the number of distinct models, not the number of workers.
```

The last line is the kernel's number from `/proc/self/statm`, not the
module's own arithmetic — `tests/test_memory_shell.py` asserts the two
agree, because accounting that never gets checked against the OS is
accounting worth distrusting.

**Content-addressed reuse.** KV and prefix state is named by the SHA-256
of its contents, so identical state has one physical copy. Two levels,
because the two questions differ: an *input index* answers "what did this
request produce last time", while the *block store* deduplicates by the
output's content. One level keyed either way loses one of the wins — the
index alone misses that different inputs often produce identical state;
content alone cannot answer a lookup by request.

Blocks are refcounted under a byte budget. A pinned block is never
evicted: freeing bytes a live session is mid-read is a use-after-free that
presents as one session receiving another's state.

## Why the sharing needs a security model

Prefix cache sharing between tenants is an information leak, and not a
theoretical one. If tenant B's request returns fast because tenant A
already cached that exact prefix, B has learned A processed that content.
Run the probe over a dictionary of candidate documents and the cache is an
oracle answering *has anyone here seen this?* about other people's inputs.

So the default is deny. State derived from a tenant's input is private to
that tenant, and identical bytes belonging to two tenants are **stored
twice on purpose**. That costs memory and it is the right trade, because
what can be shared safely is where the savings actually are:

| State | Shared? | Why |
|---|---|---|
| Model weights | Yes | Identical for everyone, public, and the largest cost. Knowing which model is loaded is not a secret. |
| Declared-public prefixes | Opt-in, per block | A system prompt the operator explicitly marks shareable. Never promoted for merely being popular. |
| Anything derived from tenant input | No | This is the channel. |

Three mechanisms enforce it:

- **Scoped lookups.** A block another tenant owns is not *refused*, it is
  *not found*. A denial that reports "forbidden" distinguishes itself from
  "absent" and is itself the signal.
- **No trace on probe.** A forbidden lookup does not count a hit or
  advance the block's recency. A denial that still updates statistics
  leaves the victim's eviction order observable.
- **Per-tenant quotas.** Without them a tenant floods the cache, forces a
  victim's working set out, and reads the victim's occupancy off the
  resulting slowdown. Quotas make a tenant's pressure land on its own
  blocks.

`test_probe_leaves_no_trace_on_the_victims_block` carries out the probing
attack — fifty lookups against a victim's block — and asserts the victim's
hit count and recency are untouched.

## The remote front end

Work that runs on the shell host does not occupy the client's RAM at all.
The front end that makes that possible deliberately **does not implement
SSH**: hand-rolled transport crypto is how components like this get
broken. It speaks line-delimited JSON over stdin/stdout and lets `sshd`
run it as a forced command, so authentication, key management and
transport encryption stay with an implementation that has been attacked
for twenty-five years.

```
# ~/.ssh/authorized_keys on the shell host
command="/usr/local/bin/memoryshell serve --budget-mib 4096",
environment="MEMORY_SHELL_TENANT=alice",
environment="MEMORY_SHELL_SHARED_SCOPES=shared:weights,shared:public",
no-agent-forwarding,no-port-forwarding,no-pty,no-X11-forwarding
ssh-ed25519 AAAAC3Nz... alice@laptop
```

`PermitUserEnvironment=yes` is required in `sshd_config` for the
`environment=` directives, and should be paired with the `no-*`
restrictions above so a key that can reach the shell cannot do anything
else with the account.

The single property everything else rests on: **the tenant comes from the
`authorized_keys` entry, never from the request.** A client that sends
`{"op": "ping", "tenant": "bob"}` is answered as whoever its key
authenticated as. A protocol that lets a caller name itself has no
isolation at all, however careful the cache underneath is.
`test_client_cannot_name_its_own_tenant` pins this.

The rest is ordinary hardening: an allow-list of three operations, an 8MiB
frame cap, no subprocess anywhere, no filesystem surface, and errors that
never echo attacker-controlled strings back into whatever reads the logs.

## macOS

`packaging/build_dmg.sh` builds `MemoryShell.dmg`: the package, a
launcher, an installer, and a launchd agent. It is a **LaunchAgent rather
than a LaunchDaemon** on purpose — it runs as the logged-in user, so the
cache stays inside one account. A system-wide daemon sharing cached state
between user accounts would be precisely the cross-tenant leak the
isolation model exists to prevent.

```bash
./packaging/build_dmg.sh --dry-run     # print every step, create nothing
./packaging/build_dmg.sh               # requires macOS (hdiutil)
./packaging/build_dmg.sh --sign "Developer ID Application: ..."
```

Notarization is not automated: it uploads your build to Apple, which
should be a decision rather than a side effect of running a script.

## The loop back to metering

`proof_of_avoided_work` needs two things it could not produce for itself:
a baseline oracle fed by measured cold costs from identified measurers,
and claims whose `actual_cost_seconds` came from an instrument rather than
a keyboard.

A cache miss is exactly a timed cold execution of a unit whose commitment
the shell already computed. A hit is exactly a reuse event, timed. So
passing a signer to `MemoryShell` makes every miss a baseline sample and
every hit a signed claim, both as a side effect of ordinary serving:

```python
shell = MemoryShell(budget, signer=keypair, oracle=oracle, settlement=engine)
```

The component that saves the memory is the one that honestly measures the
saving. That is the architecture in a sentence, and it is what turns the
credits from numbers somebody typed into numbers an instrument produced.

## What this is not

- **No model is wired in.** The shell is the caching, isolation and
  metering layer; `Computer` is the seam where a real inference runtime
  plugs in, and there is deliberately no default that executes anything a
  client supplies. The savings above are of the mechanism, measured with
  synthetic buffers — the mmap and refcounting behaviour is identical with
  real weights, but no real model has been served through this.
- **KV sharing is in-process.** Weight sharing crosses processes for free
  via the page cache; the block store is a Python object in one process.
  Multi-worker KV sharing needs a shared-memory allocator (`/dev/shm` or
  equivalent) and is not built.
- **No timing analysis.** The store closes the channel structurally — a
  forbidden probe computes, so it takes cold time and looks like a genuine
  miss — but nobody has instrumented this against an attacker with fine
  timing, and "structurally sound" is not "measured".
- **The .dmg has not been built.** It was written and dry-run on Linux,
  where `hdiutil` does not exist. The script refuses to run off macOS
  rather than emitting something that looks like a disk image and is not.
- **Eviction is LRU.** Fine as a default, not optimal; a real deployment
  wants cost-aware eviction, since a block that took 400ms to compute is
  worth more than one that took 4ms.
