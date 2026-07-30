# ADR 0002: Quality is a proxy, not semantic verification

## Status

Accepted.

## Decision

The score is named and documented as an extraction-quality proxy. Components,
deterministic validation errors, confidence, uncertainty, and the lack of a truth
guarantee are exposed with every assessment.

## Consequence

The proxy may select measured retry strategies but cannot certify that extracted
facts match the source. Domain-specific semantic verification remains a caller
responsibility.
