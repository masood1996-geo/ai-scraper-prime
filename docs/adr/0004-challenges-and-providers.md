# ADR 0004: Detect challenges and escalate

## Status

Accepted.

## Decision

Known challenge markers produce typed failures. Default recipes skip automatic
handling and escalate. The project does not implement CAPTCHA, WAF, or Cloudflare
circumvention.

External LLM providers remain opt-in configuration boundaries. Their availability,
cost, policy, and rate limits are not repository guarantees.
