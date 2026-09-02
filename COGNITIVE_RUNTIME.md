# Cognitive Runtime Doctrine

How work is done, so that a long-running system stays both informed and
small.

```text
OVERPROMPT
    ↓
OVERDELIVER
    ↓
VERIFY
    ↓
COMPRESS
    ↓
STORE
    ↓
HYPER-FORGET
    ↓
EXPAND
    ↓
CONTINUE
```

The loop exists because two failure modes sit either side of it. Load
everything and the working set is all history and no room; load nothing and
every increment re-derives what was already settled. The loop is the path
between them.

## OVERPROMPT

Load the richest relevant context — not all historical state.

The distinction is relevance, not volume. Every prior decision is available
somewhere; the ones that constrain *this* objective are the ones worth
paying for. A run that begins by reading the entire history has spent its
working set before it starts, and a run that begins by reading nothing will
rediscover a constraint the hard way.

In practice: read what the current objective touches, plus the invariants,
plus the last checkpoint. Not the transcript.

## OVERDELIVER

Produce the smallest **complete** production increment.

Smallest and complete pull against each other and both are load-bearing.
Smallest, because a large increment cannot be verified, reviewed or rolled
back as a unit. Complete, because a partial increment leaves the repository
in a state that lies — code with no tests looks finished, and a plan with
no code looks like progress.

Complete means:

```text
implementation
+ validation
+ tests
+ observability
+ receipts
+ rollback where relevant
```

An increment missing any of those is not smaller. It is unfinished, and the
missing part becomes someone else's surprise.

## VERIFY

Run the checks and record what they actually said.

The distinction that matters: *a file existing is not an implementation, and
a plan existing is not a pass.* `FOUNDATION_REPORT.md` requires a source
file, a test file, a command and a result for every claim — because those
four together are hard to fake and a green summary alone is not.

## COMPRESS

Turn completed experience into something small and durable:

- manifests
- receipts
- checkpoints
- recipes
- archetypes
- hashes
- durable summaries

Compression is where the loop pays for itself. A finished increment is
large — the reasoning, the false starts, the intermediate states — and
almost none of it is needed again. What is needed is what it concluded and
what it produced, which is a hash and a paragraph.

## STORE

Write the compressed form somewhere content-addressed, so it can be found
by what it is rather than where it was put, and verified on the way back
out.

`crates/storage` does this: objects named by SHA-256, re-hashed on every
read, schema-versioned so a record written by a newer build fails loudly
rather than being misread.

## HYPER-FORGET

Release what can be rebuilt. Keep what cannot.

The invariant is `RECONSTRUCTABLE STATE != HOT STATE`, and the rule is
`ReconstructionCost`: state that is free to rebuild may simply be dropped,
state that costs something must be written first, and state that cannot be
rebuilt at all must never fall below the temperature where it is still
readable.

Forgetting is not deletion. It is demotion with a recorded cost of return.

## EXPAND

Reconstruct only what the current objective needs.

The asymmetry is the point: compression is cheap and eager, expansion is
expensive and lazy. A system that expands everything it compressed has a
cache, not a memory model.

## CONTINUE

Update `BUILD_STATE.md` and stop at a resumable point.

Resumable is a property of the *repository*, not of anyone's memory of it.
The next increment should be able to start from the files alone.
