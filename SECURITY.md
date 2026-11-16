# Security

Gauge is a local, read-only monitor of Codex logs. It writes its own SQLite index and never needs your OpenAI API key. Run it only under the user account whose logs you intend to inspect. The MCP host controls which tools can be invoked; the underlying index includes all readable chats in the configured log directory.

Do not post vulnerabilities containing private logs, credentials or personal paths in public issues. Use GitHub's **Report a vulnerability** option if private vulnerability reporting is enabled on the repository. Otherwise open a minimal issue requesting a private contact channel without disclosing exploit details or private data.

Only the latest release is maintained initially. Codex's internal log format can change. Unsupported records may be omitted or marked unverified; the monitor is not a billing authority.
