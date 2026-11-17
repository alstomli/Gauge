# Changelog

## 0.1.2 — 2026-11-16

- State Codex-only availability in plugin metadata, opening prompts, README and MCP guidance. Check conversation type before dependency troubleshooting so ChatGPT users are directed to Codex.
- Redesign the README around compatibility, screenshots, installation, updates and troubleshooting. Default marketplace setup explicitly follows `main`.

## 0.1.1 — 2026-11-16

- Add dark/light UI screenshots using synthetic sample usage and a reproducible preview builder.
- Bundle a Gauge opening/setup skill that diagnoses missing uv, PATH differences, and dependency startup failures when MCP tools are unavailable. Expose it through plugin setup and include it in release archives.
- Synchronize Python, plugin, UI and MCP version declarations for the 0.1.1 release. uv remains required; troubleshooting skill selection depends on the host.

## 0.1.0 — 2026-11-16

- Local token, prompt-cache and estimated-credit dashboard delivered as an MCP App.
- Whole-chat, latest-call and latest-prompt cache reuse, recent-call chart and live refresh.
- Current-chat binding, response-ID deduplication, inherited-agent ownership and nested resume-checkpoint verification.
- Credit estimates by fresh input, cached input and output, with reduced-motion-aware counters.
- GitHub custom marketplace, portable dependency lock, user-owned data storage and release packaging.

Windows desktop rendering has been exercised during development. macOS and Linux desktop rendering remain unverified; CI covers portable backend, packaging and protocol behavior on those platforms when run.
