# Security review — 28 September 2026

## Scope and decision

Local fork of Knight60/ArcGIS-Pro-MCP, upstream baseline `e63d4808522171e94f913f4330fb5ce8f9e25d3b`.
User selected **read-only by default; explicitly enable reviewed editing tools**.
The local add-in version is 1.1.2 (assembly 1.1.2.0), targeting the installed ArcGIS Pro 3.7/.NET 10.

This was a catalog-wide attack-surface review followed by a deliberately restricted security profile.
It is not a claim that all 112 original tool implementations are safe or functionally tested.
All 112 catalog names have an explicit disposition below. Enabled paths, central dispatch, transports,
credentials, client registration, and relevant maintenance paths received focused review and changes.
The 94 disabled implementations and third-party GIS binaries are not approved for re-enablement.

## Findings and treatment

| Finding | Treatment |
| --- | --- |
| Unauthenticated HTTP and TCP could use the user's GIS privileges | Mandatory bearer authentication on loopback HTTP; TCP listener removed |
| Unknown commands forwarded into Python; arbitrary code, GP and batch routes bypassed narrow tools | Central fail-closed allowlist; unknown commands, batches, Python, generic GP and expression tools denied |
| Optional Python server independently exposed the same power | Python listener, relay and autostart replaced with inert/failing compatibility stubs |
| Browser requests could reach loopback | Origin, Fetch Metadata, exact Host and remote loopback checks; no browser CORS support |
| Tool schemas were advisory only | Strict required/type/range/unknown-property validation, duplicate/depth rejection, removed unsafe arguments |
| Arbitrary dataset paths accepted by normal query tools | Resolve only unique layers/tables already in the project; path fallback removed from resolution |
| Unbounded query offsets, row scans and materialized strings/groups | Row/offset/scan, attribute-size and aggregate byte budgets; reject oversized queries |
| Unlimited simultaneous work could overwhelm Pro's MCT | Eight HTTP clients maximum, one dispatch, no unbounded dispatch queue |
| Editing could happen without a distinct local permission | Default off; three layer-display edits only; local consent, 15-minute expiry, project scope, revoke and MCT recheck |
| Stop button controlled only TCP, leaving HTTP live | Ribbon now controls the actual HTTP listener; stop also revokes editing |
| Client credential/config exposure and overwritten backups | Protected current-user ACLs, atomic config writes, distinct protected backups, reparse-path refusal |
| Stdio relay followed redirects and did not check HTTP errors | Redirects/proxies disabled, bearer attached, failures checked, responses disposed |
| Python connection replayed requests after connection errors | Removed legacy transport implementation and automatic replay entirely |
| Restart helper automatically answered Don't Save | Retired; no automatic save/discard dialog handling |
| Installer offered broad add-in-policy changes/root trust | Hardened installer refuses those switches; existing Windows/Pro policy left unchanged |
| Broad empty-directory cleanup could touch unrelated directories | Only the empty package-ID directory is cleaned; other empty folders preserved |

Features such as file exports, layout/raster writes, feature edits and geoprocessing are NOT repaired merely
by hiding them in tools/list: they are denied again at dispatch, including direct calls by name.
For future expansion, add narrowly typed operations with project/output scopes, per-operation approval,
bounded resource use, and scratch-project positive/negative tests before extending the allowlist.
Do not add a general “unsafe mode” switch.

## Tests and deployment evidence

- Release add-in builds successfully on installed Pro 3.7.0.1901, without third-party NuGet dependencies.
- Real HTTP transport + real policy/router with fake GIS handlers: authentication, notification handling,
  schema/catalog filtering, all 94 denied names with an editing grant, unknown/case-variant calls, missing
  arguments, type/range/SQL/path/geometry rejection, duplicate JSON, large IDs, JSON media type, chunked
  body limit, editing grant/revocation and MCT-time revocation, concurrency, retired TCP/Python.
- Client-registration tests: all pass using fake credentials and temp configs/relay, preserving unrelated
  JSON/TOML settings, migrating old entries, and keeping distinct backups.
- Python tests: 9 pass, including assertions that retired transports do not create sockets.
- Installer parse/integrity tests and isolated package identity/uninstall tests pass.
- Codex registration `arcgis_knight60` updated using the actual credential and accepted by `codex mcp get`.
  Only that server section changed. Config and credential ACL protection verified. No token is recorded here.
- Installed candidate and source can be compared with `Get-FileHash`; final live verification is recorded below.
- The latest build is unsigned. Existing Pro policy was already `BlockAddIns=0`; no registry/certificate
  changes were made. Unrelated installed add-ins/bridges are outside this review.

### Live verification

ArcGIS was reopened with a saved synthetic fixture; no save/discard decision was automated.
Authenticated initialize confirms the running assembly is **1.1.2.0**.
The installed package and source build match SHA-256
`CD5BD42E1722C522AE6A1C6AAEF281DFCCE162F53FAC8F4A7D35024609C6752B`.

`test-hardened-installed.ps1` **passed live**: all 15 read tools, all 94 disabled names,
three editing denials in default mode, invalid SQL/path/limit denials, missing/incorrect credentials,
browser Origin rejection, and unchanged three-point fixture. Ports 6510 and 6511 have no listeners;
only 127.0.0.1:6520 is served by HTTP.sys. The separate sandbox Windows account was denied access
to the token ACL, while the credential-owning account can use it.

The local-model live test **passed**: Ollama `llama3.1:latest` selected `count_features`,
the authenticated bridge returned 3, and the local model reported the correct result.
The installed PowerShell stdio relay also **passed** initialize, 18-tool discovery,
project read, and arbitrary-code rejection. The first stdio test omitted the registrar's
per-process `-ExecutionPolicy Bypass` flag and failed under Windows PowerShell's default
script restriction; the test was corrected to match the actual configured command.
No persistent execution-policy change was made. Organizations that prohibit such launchers
should use native HTTP clients or an approved signed relay; the actual Codex connection is native HTTP.

The three enabled-in-catalog editing tools were confirmed denied live in default mode.
Positive editing grant/revocation, expiry, project-scope changes and queued MCT-time revocation
were tested with the real policy/router and fake GIS handlers, not by enabling editing in the user's live session.

Reproduction commands:

```powershell
.\scripts\test-hardened-installed.ps1
.\scripts\test-local-model.ps1
& 'C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe' .\scripts\test_hardened_stdio.py
```

The first script makes no edits: it exercises all 15 read tools on the existing three-point fixture,
checks all 94 disabled catalog tools, denies opt-in edits in read-only mode, checks credentials and
browser rejection, checks legacy listener absence, and verifies the fixture still has three rows.
The local model receives only the synthetic fixture request/result, never the bearer token.
Positive live UI permission granting/edit execution is a separate manual acceptance check;
the agent does not click a security-permission grant on the user's behalf.

### Reproduce isolated tests

```powershell
dotnet run --project tests/http-transport -p:TargetFrameworks=net10.0 -f net10.0
dotnet run --project tests/client-registration -p:TargetFrameworks=net10.0 -f net10.0
& 'C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe' -m pytest tests -q
.\tests\installer\test-script-integrity.ps1
```

.NET 8 runtime tests were not completed locally; the available SDK tried to restore reference packs from
NuGet and the sandbox TLS/network path failed. CI still declares .NET 8 and .NET 10 transport coverage.
No successful CI run, independent penetration test, vulnerability-database audit of ArcGIS/native binaries,
or complete stress test is claimed.

## Authorized client access

After ArcGIS starts the hardened package, register Codex from the ribbon or:

```powershell
dotnet run --project scripts/client-setup -- codex
```

This helper edits only the current user's `arcgis_knight60` entry, backs up the existing config and protects
the file ACL. It emits no credential values. Restart/reconnect Codex to refresh the connection and tool catalog.
The equivalent stdio relay can be generated with `dotnet run --project scripts/client-setup -- relay`.
Other MCP servers and clients are not silently changed or unregistered.

The OpenAI Docs skill informed the Codex authentication format:
[`http_headers` is a supported static-header map](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).
Credentials stay outside this repository; the checked-in `.mcp.json` intentionally registers no unauthenticated client.
Existing sessions can still call HTTP directly using the credential locally, without exposing it to the model.

The Computer Use skill governs safe app restart handling and requires leaving security-permission controls
to the user. No shell commands were typed into ArcGIS's Python window.

## Local-model use

Local Ollama `llama3.1:latest` provided two bounded review drafts. Its first draft incorrectly described
some proposed checks as absent; those claims were rejected. The second suggested basic authentication,
editing, and grant-boundary tests already represented in the suite. Local output is not security evidence.
The primary review and executable tests determine acceptance. A real local-model tool-call round trip
is covered by the live test script, separate from these review drafts.

## Remaining limits

See [SECURITY.md](../SECURITY.md) for the threat model, credential rotation, source-data confidentiality,
same-user/admin access, loopback listener impersonation, non-cancellable GIS work, unsigned deployment,
and rollback risks. Do not tunnel the port or enable arbitrary execution to “make a tool work.”
Older docs/examples and `dist/` binaries describe upstream behavior; the policy below governs this fork.

## Complete catalog disposition

Read-only means authenticated access by default. Opt-in means local consent for the current project/process,
with automatic expiry; it is still denied in default mode. Disabled means direct calls are also denied,
including after the layer-editing grant.

| Tool | Hardened disposition |
| --- | --- |
| `ping` | Authenticated read-only |
| `get_capabilities` | Authenticated read-only |
| `diagnose` | Disabled; further scoped review required |
| `get_arcgis_info` | Authenticated read-only |
| `get_project_info` | Authenticated read-only |
| `save_project` | Disabled; further scoped review required |
| `list_maps` | Authenticated read-only |
| `create_map` | Disabled; further scoped review required |
| `remove_map` | Disabled; further scoped review required |
| `activate_map` | Disabled; further scoped review required |
| `set_map_properties` | Disabled; further scoped review required |
| `get_map_extent` | Disabled; further scoped review required |
| `get_environment` | Disabled; further scoped review required |
| `set_environment` | Disabled; further scoped review required |
| `get_layers` | Authenticated read-only |
| `get_layer_info` | Authenticated read-only |
| `add_layer` | Disabled; further scoped review required |
| `add_web_layer` | Disabled; further scoped review required |
| `remove_layer` | Disabled; further scoped review required |
| `rename_layer` | Opt-in: reviewed layer display edit |
| `duplicate_layer` | Disabled; further scoped review required |
| `set_layer_visibility` | Opt-in: reviewed layer display edit |
| `set_layer_transparency` | Opt-in: reviewed layer display edit |
| `set_layer_scale_range` | Disabled; further scoped review required |
| `set_definition_query` | Disabled; further scoped review required |
| `move_layer` | Disabled; further scoped review required |
| `create_group_layer` | Disabled; further scoped review required |
| `zoom_to_layer` | Disabled; further scoped review required |
| `set_basemap` | Disabled; further scoped review required |
| `get_broken_layers` | Disabled; further scoped review required |
| `repair_layer_source` | Disabled; further scoped review required |
| `add_join` | Disabled; further scoped review required |
| `remove_join` | Disabled; further scoped review required |
| `get_features` | Authenticated read-only |
| `count_features` | Authenticated read-only |
| `get_unique_values` | Authenticated read-only |
| `get_field_statistics` | Authenticated read-only |
| `summarize_features` | Authenticated read-only |
| `insert_features` | Disabled; further scoped review required |
| `update_features` | Disabled; further scoped review required |
| `delete_features` | Disabled; further scoped review required |
| `save_edits` | Disabled; further scoped review required |
| `discard_edits` | Disabled; further scoped review required |
| `calculate_field` | Disabled; further scoped review required |
| `select_features` | Disabled; further scoped review required |
| `select_by_location` | Disabled; further scoped review required |
| `get_selection` | Disabled; further scoped review required |
| `set_selection` | Disabled; further scoped review required |
| `clear_selection` | Disabled; further scoped review required |
| `zoom_to_selection` | Disabled; further scoped review required |
| `list_fields` | Authenticated read-only |
| `add_field` | Disabled; further scoped review required |
| `add_fields` | Disabled; further scoped review required |
| `delete_field` | Disabled; further scoped review required |
| `alter_field` | Disabled; further scoped review required |
| `create_feature_class` | Disabled; further scoped review required |
| `create_table` | Disabled; further scoped review required |
| `create_file_geodatabase` | Disabled; further scoped review required |
| `truncate_table` | Disabled; further scoped review required |
| `delete_dataset` | Disabled; further scoped review required |
| `export_features` | Disabled; further scoped review required |
| `run_geoprocessing_tool` | Disabled; further scoped review required |
| `list_geoprocessing_tools` | Disabled; further scoped review required |
| `list_toolboxes` | Disabled; further scoped review required |
| `describe_geoprocessing_tool` | Disabled; further scoped review required |
| `run_python_toolbox_tool` | Disabled; further scoped review required |
| `check_extension` | Disabled; further scoped review required |
| `get_messages` | Disabled; further scoped review required |
| `set_layer_renderer` | Disabled; further scoped review required |
| `get_layer_symbology` | Disabled; further scoped review required |
| `list_color_ramps` | Disabled; further scoped review required |
| `set_layer_labeling` | Disabled; further scoped review required |
| `apply_symbology_from_layer` | Disabled; further scoped review required |
| `save_layer_file` | Disabled; further scoped review required |
| `get_map_view` | Authenticated read-only |
| `set_map_view` | Disabled; further scoped review required |
| `export_map_view` | Disabled; further scoped review required |
| `list_bookmarks` | Authenticated read-only |
| `create_bookmark` | Disabled; further scoped review required |
| `apply_bookmark` | Disabled; further scoped review required |
| `delete_bookmark` | Disabled; further scoped review required |
| `list_layouts` | Disabled; further scoped review required |
| `get_layout_info` | Disabled; further scoped review required |
| `create_layout` | Disabled; further scoped review required |
| `delete_layout` | Disabled; further scoped review required |
| `add_map_frame` | Disabled; further scoped review required |
| `set_map_frame_extent` | Disabled; further scoped review required |
| `add_layout_text` | Disabled; further scoped review required |
| `add_layout_legend` | Disabled; further scoped review required |
| `add_layout_scale_bar` | Disabled; further scoped review required |
| `add_layout_north_arrow` | Disabled; further scoped review required |
| `add_layout_picture` | Disabled; further scoped review required |
| `set_layout_element` | Disabled; further scoped review required |
| `delete_layout_element` | Disabled; further scoped review required |
| `export_layout` | Disabled; further scoped review required |
| `preview_layout` | Disabled; further scoped review required |
| `export_map_series` | Disabled; further scoped review required |
| `get_raster_info` | Disabled; further scoped review required |
| `set_raster_symbology` | Disabled; further scoped review required |
| `raster_calculator` | Disabled; further scoped review required |
| `sample_raster_values` | Disabled; further scoped review required |
| `zonal_statistics` | Disabled; further scoped review required |
| `list_workspace_contents` | Disabled; further scoped review required |
| `list_folder` | Disabled; further scoped review required |
| `describe_dataset` | Disabled; further scoped review required |
| `search_data` | Disabled; further scoped review required |
| `get_project_items` | Disabled; further scoped review required |
| `add_folder_connection` | Disabled; further scoped review required |
| `execute_arcpy_code` | Disabled; further scoped review required |
| `get_pump_status` | Disabled; further scoped review required |
| `stop_pump` | Disabled; further scoped review required |
| `run_batch` | Disabled; further scoped review required |
