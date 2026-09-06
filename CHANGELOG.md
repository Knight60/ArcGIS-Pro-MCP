# Changelog

Notable changes, newest first. Versions are the add-in version in
`addin/ArcGISProMCP/Config.daml`, which is what the ribbon, the installer and
the MCP handshake all report.

## 1.1.1 — unreleased

### Fixed

- **Codex could not be registered on a machine that had not installed the
  Python relay.** The button resolved a launcher before it drew its
  confirmation dialog, so it raised *"it needs the Python relay — and
  arcgis-pro-mcp.exe is not installed"* and wrote nothing. Codex accepts a
  Streamable HTTP server as a bare `url` in `config.toml`, with no `transport`
  key, so it now connects directly to the add-in like every other HTTP client.
  An existing `command`/`args` registration is replaced in place, including its
  `env` subtable — a table holding both `command` and `url` is rejected by
  Codex outright.
- **Claude Desktop had the same dead end.** It can only launch a server, so the
  add-in now writes the missing piece itself: a PowerShell bridge under
  `%LOCALAPPDATA%\ArcGIS Pro MCP` that forwards to the same HTTP endpoint.
  Windows PowerShell ships with Windows, so no client needs Python, Node or pip
  any more.
- **Uninstalling failed with a `CommandNotFoundException`** after deleting the
  package. `Remove-EmptyAddInFolders` had lost its definition while both call
  sites remained, and the installer runs with `$ErrorActionPreference = 'Stop'`.
- **The installer refused to run on ArcGIS Pro newer than 3.7.** Older than 3.7
  is a real barrier — the references are 13.7 — but newer is not. Below 3.7 it
  refuses; above, it warns and installs.
- **Claude Desktop was reported as not installed, and would have been given a
  config file it never reads.** The Microsoft Store build is a packaged app, so
  what it sees as `%APPDATA%` is really its own
  `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming`. The catalog now
  resolves whichever of the two layouts is on the machine.
- **Everything that named a port named the wrong one.** The Status button's
  caption, the toggle's tooltip and `ping`'s `port` field all reported 6510 —
  the legacy TCP bridge, which no AI client uses — while the address clients
  actually need, `http://127.0.0.1:6520/mcp`, appeared only on the second line
  of a dialog you had to click. An assistant asked where it was connected duly
  told its user 6510.
- **`ping` always reported `project_path: null`**, even with a project open,
  because it does not run on the Main CIM Thread and the field was hard-coded.
  A null there reads as *no project open*, so assistants told people to open a
  project they already had open. It now reads the project, and omits the key
  rather than inventing a null if that read is not possible.
- `-CheckOnly` reported a machine as *Ready* when nothing was installed.
- `README.md` claimed ArcGIS Pro 3.3+; the package has required 3.7 since the
  .NET 10 move.

### Changed

- Builds go to `artifacts/candidates/pro-<version>/` and do not deploy. `dist/`
  receives only a build that has been installed, loaded by ArcGIS Pro and
  checked over HTTP, and now carries the `build-report.json` that identifies it.
- `build.ps1` runs the transport tests on both frameworks and the installer
  tests against the package it just produced.
- The build refuses references that do not match the selected Pro version, and
  stamps `desktopVersion` from it.
- The Python package pins `mcp>=1.6.0,<2`.

## 1.1 — 2026-08-30

- Relicensed to AGPL-3.0-or-later, with a separate commercial licence and an
  additional permission for linking against the ArcGIS Pro SDK.
- Ribbon rebuilt: one start/stop toggle, a status button, one button per AI
  client showing whether it is already registered, and an Info button.
- Single-file installer: a `.cmd`/PowerShell polyglot with the add-in embedded,
  so there is nothing else to download and no execution-policy prompt.
- ArcGIS Pro 3.7 and .NET 10.

## 1.0 — 2026-08-29

First public release. Withdrawn and retagged: it went out under MIT, which was
not the intended licence.
