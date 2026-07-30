# ADR 0003: Bounded process-local recovery and SQLite strategy memory

## Status

Accepted.

## Decision

Recovery attempts and events are scoped per job and process. A step returns one of
four typed outcomes, and success requires an independently successful retry.

Domain profiles, accepted prompts, cleaning-rule evidence, and extraction history
are persisted in SQLite. Recovery attempt counters are not persisted.

## Consequence

Restarts clear recovery counters but retain measured strategies. This is suitable
for a local prototype, not coordinated distributed recovery.
