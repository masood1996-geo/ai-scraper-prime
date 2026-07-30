# ADR 0001: Keep command safety standalone

## Status

Accepted.

## Decision

AI Scraper has no shell-command execution surface. `command_safety.py` remains a
tested standalone component for future action-taking integrations. No artificial
scraper call is added merely to claim protection.

## Consequence

The active scraper does not advertise command-safety enforcement. Any future
command surface must route every action through the validator and add integration
tests before the status can change.
