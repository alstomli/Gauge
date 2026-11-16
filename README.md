# Gauge

**Tokens · Cache · Credits.** A local Codex usage monitor with an embedded MCP dashboard. See whole-chat, latest-model-call and latest-prompt cache reuse, recent call history, and estimated credits split into fresh input, cached input and output.

Gauge reads existing local logs. Collection and dashboard refresh make no model calls and need no OpenAI API key, hosted backend or separate browser dashboard. This is an independent project, not an OpenAI product or official-directory listing.

[![Release checks](https://github.com/alstomli/Gauge/actions/workflows/ci.yml/badge.svg)](https://github.com/alstomli/Gauge/actions/workflows/ci.yml)

## Requirements and platform support

- Python **3.11+**, [uv](https://docs.astral.sh/uv/getting-started/installation/), and a local Codex installation that writes compatible session logs.
- A desktop host supporting MCP Apps for the embedded panel. Other MCP clients can use the text tools; UI placement depends on the host.
- Git for GitHub marketplace installation. **Node.js is only needed to change/rebuild the UI**, not to run a release.
- Automated accounting, packaging and MCP launch/refresh checks pass on Windows, macOS and Linux with Python 3.11 and 3.13. Windows desktop rendering has been exercised during development; native desktop rendering on macOS/Linux is **not yet verified**. See [validation details](docs/VALIDATION.md).

Install uv using its official instructions and make sure `uv --version` works. Restart the desktop app after installation so its process inherits the updated PATH. First launch may download dependencies from the package registry; subsequent refreshes stay local.

## Install through the custom marketplace

Add the marketplace and install Gauge:

```sh
codex plugin marketplace add alstomli/Gauge
codex plugin add gauge@gauge-tools
```

Use a compatible Codex CLI that supports these commands. If your host exposes marketplace sources in its plugin directory, select **Gauge** under that source and install it there. This repository is a custom marketplace, separate from OpenAI's universal public directory. See [OpenAI's marketplace documentation](https://developers.openai.com/plugins/build/plugins#add-a-marketplace-from-the-cli).

Reload/restart the desktop host as needed to discover the newly installed MCP tools, then ask:

> Open Gauge for this chat.

To pin a release instead of following the default branch, add the marketplace with `--ref v0.1.0`. Do not enable both the plugin and a separately configured copy of the same MCP server. Existing installations can keep the `cache-monitor` connection key and tool names.

## Install directly from source

These commands work in PowerShell and a macOS/Linux terminal once Python, Git and uv are available:

```sh
git clone https://github.com/alstomli/Gauge.git
cd Gauge
uv sync --locked
uv run --locked gauge --version
```

Register the server using your **absolute checkout path** so it works from any project:

```sh
codex mcp add cache-monitor -- uv run --locked --no-dev --project "/absolute/path/to/Gauge" gauge mcp
```

On Windows, replace the example path with a path such as `C:/Tools/Gauge`. Alternatively, configure the equivalent stdio command in your MCP client's settings. `uv run --locked gauge config` prints JSON settings using that environment's Python interpreter for clients accepting JSON configuration. Launching `gauge mcp` in a terminal waits for MCP messages on stdin; it is not an interactive web server.

For an already-downloaded release ZIP, extract it, open a terminal in that folder, run `uv sync --locked`, then use the same registration command. A Python wheel can be installed with `python -m pip install /path/to/codex_cache_monitor-0.1.0-py3-none-any.whl`; the `gauge` and legacy `cache-monitor` entry points are equivalent. Dependencies still need to be downloadable unless already cached.

## Use the dashboard

The dashboard is bound to the opening chat's explicit ID. It never silently chooses a recently active unrelated chat. If no records exist yet, it waits for that chat. Automatic refresh runs every **two seconds while visible**; the collector waits approximately one second between scans.

- **Whole chat:** token-weighted reuse across every distinct recorded completed call, including attempts replaced by editing a prompt.
- **Latest model call:** cached/input for the newest completed call.
- **Latest prompt:** token-weighted reuse across calls attributed to the newest prompt with recorded usage. One prompt can cause several model calls.
- **Estimated credits:** fresh input (`input - cached`), cached input and output at bundled per-model Standard-speed rates. Rates are dated in the panel. Estimates exclude speed/context surcharges and other charges, and are **not billed usage or remaining plan allowance**. Unknown rates are explicitly unpriced.

The panel offers an automatic percentage axis, history range, dark/light appearance and info icons. Credit amounts animate without changing their original colors and respect reduced-motion preferences. The host owns the side-panel placement and close controls.

## Local data and configuration

| Setting | Default / override |
| --- | --- |
| Log directory | `$CODEX_HOME/sessions`, otherwise `~/.codex/sessions`; override with `--logs` |
| Usage index | `$CODEX_HOME/gauge/usage.sqlite3`, otherwise `~/.codex/gauge/usage.sqlite3`; override with `GAUGE_DATABASE` or `--database` |
| Network use | Dependency installation and opening the optional pricing link; no Gauge telemetry or refresh requests to a hosted service |

Data lives outside plugin/package files, so updates do not erase it. An older explicit `--database` path, including `.monitor/usage.sqlite3`, remains supported; Gauge does not automatically move that existing database. Stop Gauge before copying an old SQLite database, or let a new default index rebuild from the retained logs.

Gauge indexes all readable local chats in the configured directory. The opened dashboard returns only its selected chat, while the separate list tool can return other indexed summaries. Numeric usage, IDs, timestamps, model/source metadata and local paths are persisted. Prompt text, responses, tool output and credentials are not intentionally stored. Metadata requested through tools is shared with the MCP host/model. Read [PRIVACY.md](PRIVACY.md) before sharing diagnostics.

## Accounting limits

Cache reuse is `sum(cached input) / sum(input)`; cached input is already included in input. Output does not enter this percentage. Zero input is unavailable, and unfinished calls have no reported usage yet.

Response records are deduplicated by chat and response ID. Each log is checked against its own resume-checkpoint lineage, including nested segment references after edits. Missing proof stays unverified; actual counter mismatches are marked degraded. Completed calls omitted from the surviving conversation branch still count toward spent usage. Child-agent and internal-review usage remains separate from the parent chat. For snapshot-only logs, the first cumulative value is a baseline and history is explicitly partial.

Only compatible, retained local logs are covered. Archives, other devices, cloud-only calls and separate agent chats are excluded from this chat's totals. Codex's internal log format can change. This monitor is not an account-wide billing record.

## Tools

| Tool | Purpose |
| --- | --- |
| `show_cache_dashboard` | Open the embedded dashboard for an explicit current chat ID |
| `refresh_cache_dashboard` | App-only passive refresh |
| `list_cache_sessions` | List indexed chats; internal reviews hidden by default |
| `get_cache_summary` | Whole-chat, latest-call and latest-prompt readings |
| `get_cache_history` | Completed call history and prompt groups |

The package retains `cache_monitor`, distribution name `codex-cache-monitor`, resource URI `ui://cache-monitor/dashboard.html`, and existing tool/connection names for compatibility. Gauge is the displayed product name.

## Update and uninstall

For a marketplace installation, refresh its source and update/reinstall Gauge through your host. CLI equivalents on supported versions are:

```sh
codex plugin marketplace upgrade gauge-tools
codex plugin add gauge@gauge-tools
```

A tag-pinned source stays pinned until you change its reference. For a direct checkout, stop/reload the connection, pull the desired release, and run `uv sync --locked` before reconnecting.

For a marketplace uninstall, remove Gauge in the plugin UI or run `codex plugin remove gauge@gauge-tools`. For a separately registered MCP connection, run `codex mcp remove cache-monitor`. Remove the custom marketplace source separately with `codex plugin marketplace remove gauge-tools` if desired. These operations retain usage data. See [PRIVACY.md](PRIVACY.md) for deliberate deletion of Gauge's database; never delete the entire Codex home.

## Development and releases

See [CONTRIBUTING.md](CONTRIBUTING.md) for checks, [CHANGELOG.md](CHANGELOG.md) for changes, [SECURITY.md](SECURITY.md) for reporting, and [the release checklist](docs/RELEASING.md) for building and reviewing artifacts.

```sh
npm ci
npm run check
npm test
npm run build
uv run --locked python -m unittest discover -s tests -v
uv build
uv run --locked python scripts/build_release.py
```

Build the UI before Python resource tests. Release ZIPs use an explicit file allowlist and include a per-file hash manifest; `dist/SHA256SUMS` covers the generated artifacts. Never publish your development folder wholesale. Current rates are an estimate; compare accounting changes against synthetic fixtures and the target host's logs.

## License

[MIT](LICENSE). Dependencies retain their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
