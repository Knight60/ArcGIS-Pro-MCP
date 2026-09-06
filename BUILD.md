# Building from source

You do not need to build this to use it — take the
[latest release](https://github.com/Knight60/ArcGIS-Pro-MCP/releases/latest)
and see [README.md](README.md).

This page is for changing the code or producing your own build.

---

## Prerequisites

| | Version | Notes |
|---|---|---|
| **ArcGIS Pro** | 3.4 or 3.7 | Matching installation/reference assemblies are required for each build profile. |
| **.NET SDK** | Matching Pro (see below) | `dotnet --list-sdks` |
| **Python** | 3.10+ | Only used to generate the tool schema. |

You do **not** need the ArcGIS Pro SDK (the Visual Studio extension), Visual
Studio itself, or a NuGet feed. Assemblies are referenced straight out of
`ArcGIS\Pro\bin` and `bin\Extensions\*`.

### The .NET version has to match ArcGIS Pro

C# refuses to reference an assembly built for a newer framework than the
project targets. A build using 3.7/.NET 10 references cannot target 3.4 by
lowering its framework or manifest. The project checks every referenced Pro
assembly version and refuses mismatched references.

| ArcGIS Pro | `TargetFramework` | `desktopVersion` |
|---|---|---|
| 3.4 baseline | `net8.0-windows` | `3.4` |
| 3.7 native | `net10.0-windows` | `3.7` |

Esri documents forward compatibility from add-ins built for Pro 3.0–3.6 to
3.7, with clipboard/drag-and-drop caveats. Thus a single package is possible
in principle by compiling against **3.4** and testing that exact package on
both versions. It is not yet certified for this repository. See
[Esri's .NET 10 migration guide](https://doc.esri.com/en/arcgis-pro/latest/sdk/api-reference/conceptdocs/docs/ProGuide-NET-10-Upgrade.html).

To find out which one an installation needs, read `"tfm"` from
`C:\Program Files\ArcGIS\Pro\bin\ArcGISPro.runtimeconfig.json`.

Building for an older Pro without editing anything:

```powershell
.\scripts\build.ps1 -ProTargetVersion 3.4 -ArcGISProDir 'C:\ReferenceEnvironments\Pro34'
```

The directory must contain genuine matching Pro assemblies with the original
`bin` and `bin\Extensions` layout. Obtain Pro through your licensed Esri
installation environment. A .NET 8 SDK alone is insufficient. Only Pro 3.7
references have been found on the current machine.

---

## Build

```powershell
.\scripts\build.ps1
```

Build candidates end up in `artifacts\candidates\pro-3.7\` (or `pro-3.4`).
The script does not install the candidate or overwrite released files in `dist`.

| File | What it is |
|---|---|
| `ArcGISProMCP.esriAddinX` | The add-in. Double-clicking it installs it. |
| `Install-ArcGISProMCP.cmd` | One self-contained file with the add-in embedded, so there is nothing else to download. |

The steps it runs:

1. `export_tool_schemas.py` — generates `tools.json` from `catalog.py`
2. `make_icons.ps1` — draws the ribbon icons
3. `dotnet build -c Release`
4. the client-registration tests
5. signing, if `-Sign` was passed
6. the single-file installer, with the `.esriAddinX` embedded as base64

```powershell
.\scripts\build.ps1 -Sign                    # see "Signing"
.\scripts\build.ps1 -Configuration Debug
.\scripts\build.ps1 -SkipTests
```

### The edit loop

```powershell
dotnet build addin\ArcGISProMCP\ArcGISProMCP.csproj -p:DeployAddIn=true
.\scripts\restart_pro.ps1
```

Deployment is opt-in with `-p:DeployAddIn=true`. **ArcGIS Pro only loads add-ins
at startup**, so every change needs a restart. Save your project before
restarting and prefer a disposable test project for release validation.

`restart_pro.ps1` closes Pro, answering its "save changes?" prompt with *Don't
Save*, reopens the same project, and waits until the bridge answers. Pass
`-Save` to keep the changes instead.

> On a machine with add-in security turned on, every build has to be signed
> before Pro will load it:
>
> ```powershell
> .\scripts\sign_addin.ps1 -AddInPath "$([Environment]::GetFolderPath('MyDocuments'))\ArcGIS\AddIns\ArcGISPro\ArcGISProMCP.esriAddinX"
> ```

---

## Tests

```powershell
dotnet run --project tests\client-registration    # config migration and preservation
dotnet run --project tests\http-transport -f net8.0
dotnet run --project tests\http-transport -f net10.0
python -m pytest tests\                           # catalog drift, mock end-to-end
python tests\test_end_to_end_mock.py              # explicit script entry point
python scripts\test_http.py --expected-version 1.1.1.0  # installed candidate only
```

`client-registration` exercises the AI-client config writing against **copies**
in a unique temp folder, never a real config. It checks preservation of other
settings, backup contents, legacy stdio replacement, CRLF/LF files, and duplicate
prevention. JSON formatting and trailing TOML whitespace can change. The HTTP
tests use the real HTTP server and a fake GIS dispatcher on loopback port 16520;
they verify transport compatibility, not Pro API or add-in loading compatibility.

Against a live ArcGIS Pro (Pro must be open):

```powershell
python -c "import sys; sys.path.insert(0,'src'); from arcgis_pro_mcp.connection import get_connection; print(get_connection().send_command('get_capabilities', {})['data']['command_count'])"
```

---

## Upgrading ArcGIS Pro

From doing it for real, 3.5.2 (net8.0) to 3.7.1 (net10.0):

1. Change `TargetFramework` to match and build. **None of the 109 commands
   needed a single line changed** — every error was about the framework, none
   about a missing or altered API.
2. **Regenerate `gp-parameters.json`** using the new version's arcpy:

   ```powershell
   & "C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe" `
       scripts\dump_gp_parameters.py
   ```

   Do not skip this. If a tool gained a parameter in the middle of its list,
   values land in the wrong slots **with no error at all**, and the old table
   still looks like it works.

   (arcpy segfaults as it shuts down — *after* the file is written. It is not
   a failure.)
3. `.\scripts\build.ps1`, then test.

`tools.json` comes from `catalog.py` and is not tied to a Pro version.

---

## Signing

Only needed for machines with add-in security turned on. The full account of
what ArcGIS Pro actually enforces is in
[docs/addin.md](docs/addin.md#signing-the-add-in).

```powershell
.\scripts\sign_addin.ps1 -CreateCertificate -Trust -SetProSecurity   # first time
.\scripts\build.ps1 -Sign                                            # after that
.\scripts\sign_addin.ps1 -Untrust                                    # undo the trust
```

---

## Releasing

Before publishing, complete [the release validation checklist](docs/release-validation.md).
The script produces candidates only. Copy validated, signed (where required)
files from `artifacts\candidates\pro-<version>` to `dist` only after recording
runtime results and checksums. Copy `build-report.json` across with them: it
records the version, reference assembly versions and the SHA-256 of both files,
so what is published can be told apart from a later rebuild of the same source.
`dist` currently holds the validated, signed 1.1.1 build.

```powershell
.\scripts\build.ps1 -Sign
gh release create v1.1.1 `
    dist\ArcGISProMCP.esriAddinX `
    dist\Install-ArcGISProMCP.cmd `
    --title "v1.1.1" --notes-file NOTES.md
```

**CI cannot build this.** GitHub Actions has no ArcGIS Pro to reference, so
releases are built on a machine that has it and uploaded by hand. CI can still
run `tests/client-registration` and the Python tests, neither of which needs
Pro.

That is also why `dist/` is committed rather than ignored: with no CI build,
committing it is what gives people a download beside the source that made it,
and what carries a fix between releases. Commit the rebuilt artifacts along
with whatever change produced them, so the two never disagree.

**Upload the same files to the release.** A rebuild changes the assembly even
when no source did -- the compiler stamps a fresh identity every time -- so an
asset uploaded before a later build is no longer the file `dist/` holds. Both
places claiming to be the current build while disagreeing is the state worth
avoiding; replacing the assets takes a moment and settles it:

```powershell
gh release upload v1.1.1 dist\ArcGISProMCP.esriAddinX dist\Install-ArcGISProMCP.cmd --clobber
```

Set `version` in `addin/ArcGISProMCP/Config.daml` first. It appears in the
single-file installer's header and is what the installer compares against an
existing installation to tell an upgrade from a repeat run.

---

## Repository layout

```text
addin/ArcGISProMCP/     The C# add-in -- 109 of the 112 commands
  Bridge/               TCP server, MCP over HTTP, command router
  Commands/             The commands, grouped by subject
  Clients/              Registering this server with AI clients
  UI/                   Ribbon buttons
  Config.daml           Ribbon definition and version
src/arcgis_pro_mcp/     The Python MCP server (stdio)
  catalog.py            All 112 tool definitions -- the single source of truth
arcgis_pro_plugin/      The in-Pro Python bridge, for execute_arcpy_code
scripts/                Build, sign, install, icons, code generation
tests/                  client-registration (C#), catalog drift (Python)
docs/                   Architecture and the detail behind the decisions
```

### Adding a command

1. Define it in `src/arcgis_pro_mcp/catalog.py`
2. Write the handler under `addin/ArcGISProMCP/Commands/` and register it with
   `CommandRouter.Register`
3. `.\scripts\build.ps1`

`tests/test_catalog_matches_bridge.py` fails if the catalog and the handlers
disagree, in either direction.
