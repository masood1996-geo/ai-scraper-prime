# Security and privacy

## Secrets

Pass provider credentials through environment variables or constructor arguments.
Do not commit `.env` files. AI Scraper does not persist provider keys in its SQLite
database.

Logs remove URL userinfo, query strings, and fragments. Recovery metadata contains
exception type/module/status, not exception messages. Integrators should apply the
same redaction to their own surrounding logs.

## Browser data

The Prime pipeline does not persist HTML, screenshots, cookies, or local/session
storage. Browser recovery may clear cookies and storage. A caller that explicitly
requests a screenshot owns its storage and deletion policy.

## Strategy database

`~/.ai_scraper/memory.db` stores domains, URLs from extraction history, proxy
quality metrics, accepted prompt instructions, cleaning selectors, and feedback.
Treat it as application data. Use `learning=False` when domain/URL retention is not
appropriate.

## Access controls

Challenge markers are detected and escalated. Do not modify recovery recipes to
defeat CAPTCHA, WAF, Cloudflare, authentication, robots directives, rate limits, or
provider terms.

## Open WebUI

The former one-command installers were removed because they created a predictable
administrator credential. Create accounts interactively and use Open WebUI's
normal authorization controls when manually installing `open_webui_tool.py`.
