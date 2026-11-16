# Privacy

Gauge runs on your computer. Its collector reads Codex session JSONL files under `$CODEX_HOME/sessions`, or `~/.codex/sessions` by default. Reading a JSONL record temporarily puts that record in process memory, which can include conversation content; Gauge extracts usage metadata and does not intentionally store prompt text, responses or tool output.

The SQLite index stores token counts, response/chat/turn IDs, timestamps, model and source information, project and log paths, cursor state, and counter-verification metadata. It does not intentionally store credentials or account identities. The default index is `$CODEX_HOME/gauge/usage.sqlite3`, or `~/.codex/gauge/usage.sqlite3`; `GAUGE_DATABASE` or `--database` can override it. The collector indexes readable local chats, although the opened dashboard is restricted to the selected chat. The separate list tool can return summaries of other indexed chats.

Gauge has no telemetry collector, hosted backend or HTTP dashboard. Refreshes do not call a model. Usage metadata is returned to the MCP host: opening the dashboard gives the model a short usage summary and passes chart details to the host's UI; summary/history/list tools return their requested metadata to the model. The host's own privacy and retention rules apply. Project/log paths and IDs should be treated as private when sharing reports.

Installing dependencies with uv, pip or npm contacts their configured package registries. Pricing is bundled rather than fetched during refresh. Opening the published-rates link uses the host's browser integration. Those services have their own policies.

Gauge does not automatically expire indexed history. Uninstalling the plugin keeps the index so updates do not erase usage history. To erase it, first stop every Gauge MCP connection, then remove only the Gauge database you configured, together with its `-wal` and `-shm` sidecars if present. This does not remove Codex's original logs. Do not delete your entire Codex home.

Do not attach real session logs, databases or credentials to public issues. Use synthetic examples or redact identifiers, paths and content before sharing diagnostics. This project is independent of OpenAI.
