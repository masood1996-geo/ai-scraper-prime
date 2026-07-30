# Claim-status convention

- **Implemented**: reachable from a real path, performs the stated effect, its
  result is consumed, and automated tests cover success/failure behavior.
- **Partial**: useful behavior exists, but configuration, external availability,
  or coverage limits the claim.
- **Experimental**: implemented behind a bounded or opt-in path whose reliability
  is still being evaluated.
- **Standalone**: usable code exists but the active scraper does not call it.
- **Planned**: design intent without a working runtime path.
- **Unsupported**: detected or represented, but intentionally has no working
  automatic execution path.

“Learning” means local strategy persistence and measured selection. It never means
model training. “Quality” means a heuristic extraction-quality proxy. It never
means proven factual correctness.
