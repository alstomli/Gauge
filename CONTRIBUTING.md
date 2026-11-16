# Contributing

Use Python 3.11+, uv, and Node.js 20+ for development. End users do not need Node because the MCP UI is already bundled.

```sh
uv sync --locked
npm ci
npm run check
npm test
npm run build
uv run --locked python -m unittest discover -s tests -v
```

Build the UI before running Python MCP resource tests. Keep `cache_monitor/web/mcp-app.html` synchronized with `ui/`. Use synthetic JSONL fixtures; never commit personal logs, databases, credentials, absolute machine paths or local MCP account configuration.

Preserve explicit current-chat selection, response-ID deduplication, parent/child ownership, and checkpoint verification. Retain completed usage from replaced attempts: editing a prompt does not erase the tokens already used. Never make a missing or inconsistent record look verified by guessing a token count or model.

Credit estimates must separate fresh input, cached input and output, identify unknown pricing, and state their rate date. They are not billed usage or remaining allowance.

Run `python scripts/build_release.py` to create an allowlisted plugin bundle and hashes. See [the release checklist](docs/RELEASING.md). Report which operating systems and desktop hosts you actually tested; CI protocol checks do not establish that a host rendered the UI.
