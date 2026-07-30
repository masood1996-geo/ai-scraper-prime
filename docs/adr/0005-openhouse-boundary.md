# ADR 0005: OpenHouse uses an optional adapter

## Status

Accepted.

## Decision

OpenHouse Bot Prime declares an optional dependency and calls the public
`AIScraper.scrape(...)` API through `AIScraperPrimeCrawler`. The adapter is disabled
by default and strategy memory is off at that boundary unless configured.

## Consequence

The relationship is real and testable without making either repository dependent
on the other for standalone use. AI Scraper does not replace native OpenHouse
crawlers or downstream processing.
