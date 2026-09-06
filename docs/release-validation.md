# Codex HTTP and Pro 3.4/3.7 release validation

Status on 2026-09-06: **validated on Pro 3.7 and published to `dist`. Not
certified for any other Pro version** -- do not publish as dual-version support.

## Changes

Add-in 1.1.1 registers Codex at `http://127.0.0.1:6520/mcp` using a TOML
`url`, without a Python launcher. Registration replaces the previous canonical
`[mcp_servers.arcgis]` and its subtables, and backs up the existing config.
Other clients retain their transports. Existing client settings are changed
when the user registers, not automatically when installing the add-in.

Build profiles validate framework and the identities of all seven Pro reference
assemblies, and stamp the staged manifest with the selected desktop version.
Candidates and installers are separate from `dist`, and build does not deploy.
`build-report.json` records hashes and explicitly marks runtime validation pending.

## Evidence and limits

| Check | Result |
|---|---|
| Installed reference environment | Pro 3.7, ArcGIS.Core file 13.7.0.1901, assembly 13.7.0.0, .NET 10 |
| Pro 3.4 reference environment | Not found in the inspected installation/workspace locations; required before compile audit |
| Pro 3.7 Release compilation | Passed, zero warnings/errors |
| Client registration | 27 checks passed, including LF/CRLF migration, exact pre-write backup, unrelated settings, repeat registration and EOF header |
| HTTP source integration | Passed on .NET 8 and .NET 10 with real HttpListener and fake GIS dispatcher; no Pro API validation |
| Candidate loaded in Pro 3.7 | Signed 1.1.1 installed, Pro restarted, bridge reports 1.1.1.0; initialize, notification, ping, 112 tools and read-only get_project_info passed |
| Codex Streamable HTTP | `codex.exe` accepts a bare `url` (no `transport` key) and its rmcp client completed the session against the live add-in: no transport errors, while a dead port produced `worker quit with fatal` immediately |
| Installer round trip | `-CheckOnly`, `-Uninstall`, `-Reinstall` all exit 0; uninstall removes the package and the empty add-in id folder RegisterAddIn.exe leaves behind |
| Wrong-reference rejection | Both build.ps1 and direct csproj reject target 3.4 against installed 3.7 references |
| Python unit tests | 8 passed |
| Python mock end-to-end | Passed with MCP SDK 1.29.1, including tool arguments, error hints and image output |
| Fresh Python dependency resolution | Found MCP 2.x incompatibility with existing FastMCP import; bound dependency to `mcp>=1.6.0,<2` |
| Codex model-driven tool call | Not run: the test account hit its Codex usage limit. Transport and configuration are verified; the model layer is not |
| Install from the released file alone | Simulated on this machine: only `Install-ArcGISProMCP.cmd` in a folder, carrying a download's Mark-of-the-Web, no repository and no `.esriAddinX` beside it. Installed, Pro restarted, bridge answered 1.1.1.0 |
| Codex on a machine with no relay | Virgin `CODEX_HOME`, config holding only the bytes the ribbon button writes: `codex mcp list` resolved it, the session connected with no transport error, and no `arcgis-pro-mcp.exe` process was spawned |
| Untrusted publisher at default security | Not simulated: this machine keeps `BlockAddIns` = 1 with the build certificate trusted. A machine that trusts neither, at the default 0, is untested |
| Installation on a machine other than the build machine | Pending |
| Pro 3.4 compilation/runtime | Pending genuine 3.4 references and runtime |
| Single package on both runtimes | Not certified |

The current machine has .NET SDKs 8.0.424 and 10.0.400. Transport tests on
.NET 8 do not establish compatibility of the ArcGIS-dependent command handlers.
No custom Clipboard, BinaryFormatter, DragInfo or DropInfo usage was found in
the C# source audit; a 3.4 compile is still needed to identify newer Pro APIs.

## Geoprocessing blocks a single-package claim

`Resources/gp-parameters.json` is a static tool/parameter-order table captured
from a Pro environment. It has no embedded version provenance. It must not be
assumed valid for 3.4 merely because the add-in compiles or loads. Newer tools
and inserted parameters can make named arguments execute in the wrong slots.

For separate packages, generate the table using each target installation's
arcpy (`scripts/dump_gp_parameters.py`), archive its source Pro version and hash,
then build that target. For one package, first compare tables generated from
3.4 and 3.7 and implement runtime-specific table selection or another verified
runtime parameter-resolution strategy. Test named and positional GP calls on
both versions, including tools whose parameter order differs. Recompiling
against 3.4 alone does not resolve this runtime data issue.

## Required runtime checks before distribution

1. Build with genuine target references. For the shared-package approach, use
   3.4/net8.0-windows/desktopVersion 3.4 and resolve all compilation errors
   without importing 3.7 assemblies. Record reference versions and table hashes.
2. Use disposable projects on clean Pro 3.4 and 3.7 machines. Install the exact
   candidate, preserving unsaved work before restarting. Record the package
   SHA256, Pro patch version and installed add-in version. A successful test
   against an already running older add-in does not validate the candidate.
3. Register Codex from the ribbon. If an old stdio registration exists, remove
   and re-add it with the updated add-in. Verify there is one arcgis table with
   the HTTP URL, a backup, and no command/args/env for the old relay. Test on a
   machine without `arcgis-pro-mcp.exe` installed. Restart Codex and verify
   `/mcp`, tool discovery, and a read-only `get_project_info` call.
4. Run `python scripts/test_http.py --expected-version 1.1.1.0`. Test representative
   layer/map reads, selection/edit/undo, symbology, layout export, raster, and GP
   named/positional calls in the disposable project. Compare results on both Pro
   versions. Confirm missing licenses and unavailable tools return useful errors.
5. Check Claude Code and Antigravity HTTP regression. Confirm the optional
   in-Pro Python fallback at 6511 is distinct from the external stdio relay;
   native C# tools must work without either Python component.
6. Verify install/reinstall/uninstall, restart/reconnect, and add-in trust under
   the target organization's policy. A self-signed certificate is not trusted
   on another machine automatically. Do not change trust/security implicitly.
7. If signing is required, sign the candidate, rebuild its embedded installer
   from the signed package, and record final hashes. Complete all required
   runtime checks on that exact package before copying files into `dist` or
   uploading a release. `-SkipTests` is for development, not release acceptance.

## Sources

- [Official Codex MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli): Streamable HTTP uses `url` in the MCP server table.
- [Esri .NET 10 migration](https://doc.esri.com/en/arcgis-pro/latest/sdk/api-reference/conceptdocs/docs/ProGuide-NET-10-Upgrade.html): older 3.x add-ins can run on 3.7; clipboard/drag-and-drop binary data has caveats.
