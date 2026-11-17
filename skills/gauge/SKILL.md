---
name: gauge
description: Open Gauge (token usage, prompt-cache reuse and cost estimates) for the current Claude Code session or local Codex chat, explain that ChatGPT and claude.ai conversations are unsupported, or diagnose missing Gauge tools and local startup dependencies.
---

# Gauge

## Check supported conversation type first

Gauge supports **Claude Code sessions** and **local Codex chats**, because both write local usage logs. ChatGPT conversations and claude.ai chats are not supported, on web, desktop, or mobile. A desktop app may contain several modes; its branding or window title alone does not establish the conversation type.

When the context identifies the current conversation as ChatGPT or a claude.ai chat, respond:

> Gauge works only in Claude Code sessions and local Codex chats, because it reads their local usage logs. It can't open in this conversation. Open a Claude Code session or a local Codex chat and ask "Open Gauge for this chat."

Stop there. Do not attempt a dashboard call, ask for a conversation ID, recommend installing uv, or suggest reconnecting Gauge for that unsupported conversation.

For a Claude Code session or a local Codex chat, continue below. Missing tools or a missing session-ID variable alone do not prove the conversation is unsupported.

## Find the current chat ID

- **Claude Code:** the session ID is `${CLAUDE_SESSION_ID}`. If the previous sentence shows a literal placeholder instead of a UUID, read the `CLAUDE_CODE_SESSION_ID` environment variable (`echo $CLAUDE_CODE_SESSION_ID`, or `$env:CLAUDE_CODE_SESSION_ID` in PowerShell).
- **Codex:** use the chat context or `CODEX_THREAD_ID`.

Never substitute the most recently active chat or guess from transcript file names.

## Startup

Gauge's local MCP server starts with `uv run --locked --no-dev --project <plugin-root> gauge mcp`, from the plugin's `mcp.json` (Codex) or `.claude-plugin/plugin.json` (Claude Code).
If `uv` cannot be found by the desktop app, the server never starts and none of its tools are registered. A failed tool lookup alone does not establish whether Gauge is installed, disconnected, or missing a dependency. This bundled skill can guide diagnosis without a running MCP server.

## Open the dashboard

Discover Gauge's `show_cache_dashboard` tool and call it with the current chat's explicit ID (see above). If the tool is available, use it directly without running setup checks.

Hosts that support MCP Apps render the dashboard. Where the host shows only the tool's text (for example the Claude Code terminal), report that text: cache reuse, cached and total input tokens, cache writes and completed calls. For per-prompt or per-model detail, call `get_cache_history` or `get_cache_summary` with the same ID. For Claude Code, cost figures are API-equivalent list prices, not what a subscription bills.

### Dashboard refresh fails in the Claude desktop Code tab

If the dashboard reports `MCP error -32603: IPC not available for MCP tool call`, or "Auto refresh unavailable", the server is running and the dashboard reached the desktop app; the app could not forward the dashboard's own tool calls. This is a known Claude desktop bug (anthropics/claude-code#106708) for MCP servers that Claude Code starts, including this plugin. Do not suggest reinstalling Gauge or installing uv for it.

- Explain that calling `show_cache_dashboard` again from the conversation still returns current readings.
- For automatic refresh, the user can add Gauge to the desktop app's own `claude_desktop_config.json` (Claude desktop: **Settings → Developer → Edit Config**) under `mcpServers`, with `command` set to the absolute uv path and `args` `["run", "--locked", "--no-dev", "--project", "<absolute Gauge root>", "gauge", "mcp"]`, then fully quit and reopen the app. That file holds other app settings, so add the entry without replacing them, and change it only with the user's approval.
- When both this plugin's tools and a desktop-config Gauge server's tools are available in the Code tab, open the dashboard with the desktop-config server's `show_cache_dashboard`.

If Gauge's tools are unavailable, perform the startup checks below before suggesting a reconnect or reinstall. An empty plugin search is not evidence that a local plugin is absent.

## Setup or unavailable tools

Use read-only checks first. The installed plugin root is two directories above this skill file. Read its `mcp.json` or `.claude-plugin/plugin.json` if the launch command differs from the one above.

1. Check whether `uv` resolves and runs: `command -v uv` then `uv --version` on macOS/Linux; `Get-Command uv -ErrorAction SilentlyContinue` then `uv --version` in PowerShell.
2. If lookup fails, check likely existing locations before saying it is not installed: `~/.local/bin/uv`, `~/.cargo/bin/uv`, `/opt/homebrew/bin/uv`, and `/usr/local/bin/uv` on macOS/Linux; the corresponding `uv.exe` paths under the user's `.local/bin` and `.cargo/bin`, plus pip's `%APPDATA%/Python/Python*/Scripts/uv.exe` locations on Windows. Run an existing binary with `--version` using its absolute path.
3. Distinguish the observed result:
   - **No executable found:** Explain that Gauge could not start because its required launcher, `uv`, is unavailable. On macOS/Linux, offer Astral's installer command: `curl -LsSf https://astral.sh/uv/install.sh | sh`. On Windows, link to the [official uv installation instructions](https://docs.astral.sh/uv/getting-started/installation/). After installation, have the user fully quit and reopen the desktop app, then try Gauge again. Do not require Homebrew or a separate Python installation; uv can provision a compatible Python. Say "not found in PATH or the usual install locations" rather than claiming a complete disk search.
   - **Executable exists outside PATH:** Identify the existing installation and explain that the launcher cannot resolve it through PATH. Guide a PATH correction and full desktop-app restart; reinstalling Gauge is not the first remedy.
   - **uv works in the shell:** Do not assume the desktop app inherited the same PATH. Check available MCP startup diagnostics, limiting inspection to Gauge's startup error. If the app reports that `uv` cannot be found, explain the PATH difference. If no startup diagnostics are available, state that the cause is unconfirmed.
4. For a setup/repair request, explain before running the finite check `uv run --locked --no-dev --project <absolute-plugin-root> gauge --version`: it may download Python and dependencies and create the plugin's environment. Use the resolved uv path. Report a concrete network, dependency, permission, or Python provisioning failure if this check fails. Do not run `gauge mcp` as a terminal diagnostic; it waits for protocol input. A successful version check verifies the shell environment, not tool registration in the desktop host.
5. After prerequisites work, check the plugin's enabled state and request a host reload/reconnect if its tools remain unavailable. In Claude Code, `/mcp` shows the server's status and lets the user reconnect it; `claude --debug` prints MCP startup errors. If host controls or startup diagnostics are inaccessible, give the specific remaining action and explain what has and has not been verified.

When shell checks are unavailable, describe missing uv as a possibility, not a confirmed diagnosis, and give `uv --version` as the next check. Do not finish with only "tools aren't available; reconnect Gauge." Give the observed cause, the remedy, and whether a desktop restart is needed. Never claim the dashboard opened until its tool succeeds.
