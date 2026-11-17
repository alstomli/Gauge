---
name: gauge
description: Open Gauge for the current Codex chat, set up Gauge, or diagnose missing Gauge tools and local startup failures, including a missing uv executable.
---

# Gauge

Gauge's local MCP server starts with `uv run --locked --no-dev --project <plugin-root> gauge mcp`.
If `uv` cannot be found by the desktop app, the server never starts and none of its tools are registered. A failed tool lookup alone does not establish whether Gauge is installed, disconnected, or missing a dependency. This bundled skill can guide diagnosis without a running MCP server.

## Open the dashboard

Discover Gauge's `show_cache_dashboard` tool and call it with the current chat's explicit ID. Obtain that ID from the chat context or `CODEX_THREAD_ID`; never substitute the most recently active chat. If the tool is available, use it directly without running setup checks.

If Gauge's tools are unavailable, perform the startup checks below before suggesting a reconnect or reinstall. An empty plugin search is not evidence that a local plugin is absent.

## Setup or unavailable tools

Use read-only checks first. The installed plugin root is two directories above this skill file. Read its `mcp.json` if the launch command differs from the one above.

1. Check whether `uv` resolves and runs: `command -v uv` then `uv --version` on macOS/Linux; `Get-Command uv -ErrorAction SilentlyContinue` then `uv --version` in PowerShell.
2. If lookup fails, check likely existing locations before saying it is not installed: `~/.local/bin/uv`, `~/.cargo/bin/uv`, `/opt/homebrew/bin/uv`, and `/usr/local/bin/uv` on macOS/Linux; the corresponding `uv.exe` paths under the user's `.local/bin` and `.cargo/bin`, plus pip's `%APPDATA%/Python/Python*/Scripts/uv.exe` locations on Windows. Run an existing binary with `--version` using its absolute path.
3. Distinguish the observed result:
   - **No executable found:** Explain that Gauge could not start because its required launcher, `uv`, is unavailable. On macOS/Linux, offer Astral's installer command: `curl -LsSf https://astral.sh/uv/install.sh | sh`. On Windows, link to the [official uv installation instructions](https://docs.astral.sh/uv/getting-started/installation/). After installation, have the user fully quit and reopen the desktop app, then try Gauge again. Do not require Homebrew or a separate Python installation; uv can provision a compatible Python. Say "not found in PATH or the usual install locations" rather than claiming a complete disk search.
   - **Executable exists outside PATH:** Identify the existing installation and explain that the launcher cannot resolve it through PATH. Guide a PATH correction and full desktop-app restart; reinstalling Gauge is not the first remedy.
   - **uv works in the shell:** Do not assume the desktop app inherited the same PATH. Check available MCP startup diagnostics, limiting inspection to Gauge's startup error. If the app reports that `uv` cannot be found, explain the PATH difference. If no startup diagnostics are available, state that the cause is unconfirmed.
4. For a setup/repair request, explain before running the finite check `uv run --locked --no-dev --project <absolute-plugin-root> gauge --version`: it may download Python and dependencies and create the plugin's environment. Use the resolved uv path. Report a concrete network, dependency, permission, or Python provisioning failure if this check fails. Do not run `gauge mcp` as a terminal diagnostic; it waits for protocol input. A successful version check verifies the shell environment, not tool registration in the desktop host.
5. After prerequisites work, check the plugin's enabled state and request a host reload/reconnect if its tools remain unavailable. If host controls or startup diagnostics are inaccessible, give the specific remaining action and explain what has and has not been verified.

When shell checks are unavailable, describe missing uv as a possibility, not a confirmed diagnosis, and give `uv --version` as the next check. Do not finish with only "tools aren't available; reconnect Gauge." Give the observed cause, the remedy, and whether a desktop restart is needed. Never claim the dashboard opened until its tool succeeds.
