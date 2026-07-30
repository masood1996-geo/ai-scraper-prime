# AI Scraper Prime implementation status

## Safe one-sentence description

AI Scraper Prime is a prototype extraction workflow with rendered-page fetching,
typed failures, bounded recovery, domain-scoped SQLite strategy memory, an explicit
heuristic quality proxy, measured prompt refinement, and reversible cleaning rules.

## Fully implemented

- Browser and pre-fetched HTML paths reaching structured LLM extraction.
- Typed browser, challenge, LLM provider, extraction, and JSON parse failures.
- Stable classifier using error types and status codes with an `unknown` fallback.
- Recovery context changes consumed by the actual next wait, content limit, browser
  session, or model request.
- Typed recovery step results and success emitted only after a verified retry.
- Quality component scores, deterministic validators, confidence, and uncertainty.
- Candidate/accepted/rejected/rolled-back prompt lifecycle with domain/schema
  isolation, minimum improvement, token counts, and latency.
- SQLite domain history, exponential moving average, timing bounds, and feedback.
- Redacted URL and error diagnostics.
- Unit/mocked integration tests and CI quality gates.

## Experimental

- Automatic cleaning-rule proposals and activation after repeated evidence.
- Automatic timing adjustments based on proxy quality.
- The opt-in OpenHouse Prime adapter.

## Standalone

- `command_safety.py`: tested validator for action-taking integrations; the scraper
  executes no commands.
- `open_webui_tool.py`: compatibility tool with its own extraction path.

## Partial

- Fallback-model recovery requires a caller-configured model.
- Heuristic cleaning-rule proposals recognize a deliberately narrow set of repeated
  promotion/newsletter class patterns.
- Schema validators are deterministic but cannot cover domain-specific truth.

## Unsupported

- CAPTCHA, Cloudflare, AWS WAF, or other access-control circumvention.
- Claims of semantic truth, universal extraction, zero maintenance, or production
  uptime.
- Durable distributed recovery state. Attempt counters/events are process-local;
  accepted strategies are SQLite-persistent.

## Claim-to-code matrix

| Claim | Code | Reachable path | Effect consumed | Tests | Status |
| --- | --- | --- | --- | --- | --- |
| Structured extraction | `core.py`, `llm.py` | `AIScraper.scrape` | results returned or enter batch/OpenHouse | LLM/core integration | Implemented |
| Browser rendering | `browser.py` | `scrape` without `raw_html` | page source is cleaned and extracted | browser/core integration | Implemented |
| Typed failure classification | `errors.py`, `recovery.py` | failed browser/LLM operation | recipe or escalation selected | classification tests | Implemented |
| Recovery effects | `core.py`, `recovery.py` | failed `scrape` | retry consumes changed dependency/context | recovery/core integration | Implemented |
| Verified recovery success | `recovery.py` | `recover_from_error` | success event follows returned retry | event-order tests | Implemented |
| Prompt refinement | `learner.py`, `memory.py`, `core.py` | low proxy score | accepted prompt reused later | acceptance/regression tests | Implemented |
| Cleaning-rule learning | `learner.py`, `memory.py`, `core.py` | repeated poor output | active rule changes later cleaned text | cross-run integration test | Experimental |
| Quality scoring | `learner.py` | every learned scrape | retry/acceptance/timing decisions | quality tests | Implemented proxy |
| Command safety protection | `command_safety.py` | no scraper path | none | standalone tests | Standalone |
| Challenge bypass | none | none | none | escalation tests | Unsupported |
| OpenHouse integration | OpenHouse `ai_scraper_prime.py` | opt-in fallback | records enter OpenHouse pipeline | adapter contract tests | Experimental |

## Known limitations

- Live websites and providers change independently of this code.
- Valid empty output can still mean either no matching records or a source-specific
  extraction miss; callers needing stronger certainty should add source validators.
- Strategy persistence is local SQLite, not a multi-process coordination service.
- The browser engine requires compatible local Chrome tooling.
- No repository test can establish operational uptime.

## Test evidence

The local suite covers memory CRUD/EMA, quality components, prompt acceptance and
regression rejection, timing bounds, cleaning evidence/rollback, classification,
attempt limits, real handlers, missing-handler behavior, context propagation, LLM
JSON/code fences, schema retrieval, CLI smoke, successful scrape, poor-output
improvement, browser restart, fallback model, recovery exhaustion, domain memory,
batch isolation, and cross-run cleaning rules.
