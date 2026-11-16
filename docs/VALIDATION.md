# Release validation

Date: 2026-11-16. Version: Gauge 0.1.0. Local tests use synthetic logs and disposable profiles.

| Check | Result |
| --- | --- |
| Python accounting, recovery, checkpoint, privacy, MCP and release tests | 21 passed on Windows / Python 3.13 |
| JavaScript syntax and UI unit tests | Passed; all five test files passed |
| UI build and dependency notices | Bundled HTML rebuilt; licenses included for all four bundled third-party packages |
| Extracted plugin | Locked dependency installation, actual manifest stdio launch, tool discovery, UI-resource read, verified usage and live append/refresh passed |
| Custom marketplace | Added source and installed `gauge@gauge-tools` using Codex CLI in an isolated Codex home |
| Installed Python wheel | Imported outside the development checkout; version and packaged UI resource verified |
| Distribution audit | Plugin ZIP, wheel and source distribution exclude local settings, usage databases, environments, real chat ID and developer home paths; hashes checked |
| Cross-platform CI | All six Python 3.11/3.13 jobs passed on Windows, macOS and Linux, including unit checks, package builds and extracted-plugin MCP/live-refresh tests |
| macOS / Linux desktop UI | Native panel rendering remains unverified; protocol success alone is not a rendering test |
| GitHub | See [CI runs](https://github.com/alstomli/Gauge/actions/workflows/ci.yml) and the [release](https://github.com/alstomli/Gauge/releases/tag/v0.1.0) for publication results |

The CI workflow targets Python 3.11 and 3.13 on Windows, macOS and Linux. Only a completed run establishes those matrix results. UI-resource/protocol checks do not prove that a particular desktop host rendered the panel.
