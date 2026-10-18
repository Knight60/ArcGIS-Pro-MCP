# Changelog

Notable changes, newest first. Versions are the add-in version in
`addin/ArcGISProMCP/Config.daml`, which is what the ribbon, the installer and
the MCP handshake all report.

## 1.2.0 — unreleased

Development builds of this version were used for the paper's pilot runs and are
identified there by the first 8 hex digits of the add-in's SHA-256: `c0a91663`
(ArcPy through Calculate Value, port 6520 only), `fda07d92` (activate_map and
save_edits fixes) and `81bfbdcb` (sys.executable fix). All three still reported
version 1.1.1.

### Fixed

- **Code that ran `sys.executable` started a second ArcGIS Pro and froze the
  first.** Inside Pro, `sys.executable` is `ArcGISPro.exe`, so the common
  `subprocess.run([sys.executable, "-m", "pip", ...])` in `execute_arcpy_code`
  opened a new, empty Pro and waited for it on the Main CIM Thread. While user
  code runs, `sys.executable` now points at the environment's `python.exe`, and
  `input()` gets an empty stdin instead of waiting for a console.
- **`activate_map` froze ArcGIS Pro for good.** It ran on the Main CIM Thread
  and waited there for the map pane to open, but opening a pane is UI-thread
  work that itself queues onto the Main CIM Thread, so each waited for the
  other. Every later tool call timed out and Pro could not be closed, only
  killed. The map is now read on the Main CIM Thread and the pane opened on the
  UI thread, with neither blocking the other.
- **`save_edits: true` on `insert_features`, `update_features` and
  `delete_features` waited for the save on the Main CIM Thread**, the same
  pattern, although saving edits belongs on the UI thread. The edit now
  finishes first and the save follows on the UI thread.
- **"Stop bridge" did not stop what AI clients connect to.** The ribbon's
  Start/Stop button, its Status caption and "Requests served" all read the
  legacy TCP bridge on 6510, while every AI client uses the MCP endpoint on
  6520. Pressing Stop left clients connected behind a ribbon that said "Not
  running", and the request count stayed at zero however busy the assistant
  was. The button and Status now control and report the MCP endpoint itself.
- **`execute_arcpy_code` -- the third layer -- was missing for almost
  everyone.** It lived in the optional Python bridge, which has no button: it
  had to be started from Pro's Python window every session, and its auto-start
  hook needs administrator rights and does not start the dispatcher that
  reaches the open project. It now runs inside the add-in, through the
  ModelBuilder tool Calculate Value, with the open project available, variables
  kept between calls and `print()` output returned -- about 0.05 s a call after
  the first, against seconds to ~28 s through the bridge. The Python bridge
  remains a fallback if Calculate Value ever stops running code. Tested on
  ArcGIS Pro 3.7.1; see docs/addin.md.
- **The Python bridge and the add-in were set up to collide on port 6510.**
  When the C# add-in took over 6510 for its own TCP bridge in 1.0, the Python
  bridge kept 6510 as its default, and so did the auto-start hook and the
  installer. The bridge only came up at all because it slides to the next free
  port, landing on 6511 -- the one port the add-in looks on, but one nothing
  ever configured. Anyone starting it on its default with that slide turned
  off, or with 6511 taken, got a bridge the add-in could not find, and
  `execute_arcpy_code` -- the third layer -- dropped out with only the
  "not listening" error to show for it. The bridge now has a port of its own,
  **6521**, beside the MCP endpoint on 6520: its default, the auto-start hook,
  the installer, the address the add-in forwards to, and the error that tells
  you how to start it all say 6521. Restart a bridge left running on the old
  port after upgrading. Nothing changes for AI clients: they still connect to
  `http://127.0.0.1:6520/mcp`.
- **The README said the add-in listens on the Python fallback port.** It does
  not: the add-in connects to that port, and only the Python bridge listens on
  it.

### Removed

- **The TCP bridge on 6510.** The add-in now opens one port, 6520, the one the
  ribbon shows and every AI client uses. The `arcgis-pro-mcp` stdio relay and
  the scripts that spoke to 6510 (`restart_pro.ps1`, `make_demo_gif.py`) now
  send MCP calls to 6520 instead, and fall back to a Python bridge only when no
  add-in is running. `ping` and `diagnose` no longer report a TCP port. A setup
  that still points something at 127.0.0.1:6510 should point it at
  `http://127.0.0.1:6520/mcp`.

## 1.1.1 — 2026-09-07

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
