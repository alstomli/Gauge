# Release checklist

The repository is `alstomli/Gauge` (public, MIT). This project distributes a custom marketplace; it is separate from OpenAI's public plugin directory. Building artifacts locally does not publish them.

1. Review the source and all release inputs. Never upload the entire development folder. Confirm `LICENSE`, publisher metadata, repository links, version numbers and privacy wording.
2. Run `npm ci`, `npm run check`, `npm test`, then `npm run build` in that order. Commit the generated HTML with the source.
3. Run `uv sync --locked`, `uv run --locked python -m unittest discover -s tests -v`, and the CI matrix on Windows, macOS and Linux. Run the embedded panel in a compatible desktop host for each OS you intend to claim as supported. Record results below; protocol success alone is insufficient.
4. Build Python artifacts with `uv build`. Then run `uv run --locked python scripts/build_release.py`. This creates the plugin ZIP, its per-file `release-manifest.json`, and `dist/SHA256SUMS`. The ZIP contains only explicit public inputs, including the prebuilt UI; it excludes data, machine settings and installed environments.
5. Extract the ZIP into a new directory, install its locked dependencies, and start its actual manifest launch command. Exercise tool discovery, UI resource loading, explicit chat selection, synthetic live appends and shutdown. Confirm no database is written into the installed package.
6. Test marketplace discovery and installation in a disposable Codex home. Test the normal user flow in the desktop app, including the prerequisite that `uv` is on the application's PATH. Close/restart the app after installing uv if necessary.
7. Review `dist/SHA256SUMS` and the archive manifest. Create the public GitHub repository only after confirming owner and visibility. Initialize/push the reviewed source. Do not run `git add .` against an unreviewed development folder. Confirm ignored private directories are absent from tracked files.
8. Run GitHub Actions and inspect all matrix results. Fix failures before publishing. Set the tag to `v<version>` only after the versions in Python, the UI package and the plugin manifest agree. Update `CHANGELOG.md` and this validation record.
9. Create the GitHub release from the reviewed tag and attach the plugin ZIP, wheel, source distribution and checksum file produced by CI. Verify the marketplace is reachable via `codex plugin marketplace add alstomli/Gauge --ref v<version>` and install `gauge@gauge-tools`.
10. Announce the supported platforms, installation prerequisites, accounting limits and issue-reporting instructions. Do not describe this custom marketplace as an OpenAI-approved public-directory listing.

## Validation record

- Windows: existing Gauge panel exercised during development; release-candidate clean-install, marketplace install, protocol, wheel and privacy checks passed. See [the validation record](VALIDATION.md).
- macOS/Linux: native desktop rendering not yet tested. CI configuration is supplied; results exist only after CI actually runs.
- GitHub publication and CI history: see the repository's [Actions](https://github.com/alstomli/Gauge/actions/workflows/ci.yml) and [Releases](https://github.com/alstomli/Gauge/releases) pages.

## Updates

Increment the Python (`pyproject.toml` and `cache_monitor/__init__.py`), plugin (`plugin.json`), UI (`package.json` and lock), and MCP App identity versions together. Rebuild the UI. Regenerate `uv.lock` and `requirements.lock` when dependency metadata changes. Keep the tool names, connection key and resource URI stable unless documenting a migration.

For a default-branch marketplace installation, users refresh the marketplace and reinstall/update the plugin using their host. A tag-pinned marketplace stays on that tag until users change its source reference. Stored usage is outside plugin files, so updating does not erase it.

Official documentation: [custom marketplaces](https://developers.openai.com/plugins/build/plugins), [MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).
