// Some MCP Apps hosts render the dashboard but cannot route tool calls made by
// the app itself (for example, "MCP error -32603: IPC not available for MCP
// tool call" in the Claude desktop Code tab when the server is started by
// Claude Code). Retrying cannot succeed in that host, so the dashboard switches
// to snapshot mode instead of reporting a failure every refresh interval.
const UNAVAILABLE_PATTERNS = [/IPC not available/i, /not available for MCP tool call/i];

export const SNAPSHOT_MESSAGE =
  'This app shows Gauge as a snapshot and does not let the dashboard refresh itself. Ask Claude to open Gauge again for new readings.';

export function isHostCallUnavailable(error) {
  if (!error) return false;
  if (error.code === -32601) return true; // host does not implement tools/call for apps
  const message = String(error.message ?? error);
  return UNAVAILABLE_PATTERNS.some(pattern => pattern.test(message));
}
