# Building from source

You do not need to build this to use it. Download the installer from
[Releases](https://github.com/Knight60/ArcGIS-Pro-MCP/releases) and see
[README.md](README.md).

This page is for changing the code or producing your own build.

---

## Prerequisites

| | Version | Notes |
|---|---|---|
| **ArcGIS Pro** | 3.3 or later | Required. The project references Pro's own assemblies by path. |
| **.NET SDK** | Matching Pro (see below) | `dotnet --list-sdks` |
| **Python** | 3.10+ | Only used to generate the tool schema. |

You do **not** need the ArcGIS Pro SDK (the Visual Studio extension), Visual
Studio itself, or a NuGet feed. Assemblies are referenced straight out of
`ArcGIS\Pro\bin` and `bin\Extensions\*`.

### The .NET version has to match ArcGIS Pro

C# refuses to reference an assembly built for a newer framework than the
project targets, so **each .NET generation of Pro needs its own build**. This
is not because the API changed; it has not.

| ArcGIS Pro | `TargetFramework` | `desktopVersion` |
|---|---|---|
| 3.3 – 3.6 | `net8.0-windows` | `3.3` |
| **3.7+** | **`net10.0-windows`** | `3.7` |

To find out which one an installation needs, read `"tfm"` from
`C:\Program Files\ArcGIS\Pro\bin\ArcGISPro.runtimeconfig.json`.

Building for an older Pro without editing anything:

```powershell
dotnet build addin\ArcGISProMCP\ArcGISProMCP.csproj -p:TargetFramework=net8.0-windows
```

The build has to happen on a machine with that version of Pro installed.

---

## Build

```powershell
.\scripts\build.ps1
```

Everything a release needs ends up in `dist\`:

| File | What it is |
|---|---|
| `ArcGISProMCP.esriAddinX` | The add-in. Double-clicking it installs it. |
| `Install-ArcGISProMCP.ps1` | One self-contained file with the add-in embedded, so there is nothing else to download. |

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
dotnet build addin\ArcGISProMCP\ArcGISProMCP.csproj
.\scripts\restart_pro.ps1
```

`dotnet build` deploys to the add-in folder on its own, but **ArcGIS Pro only
loads add-ins at startup**, so every change needs a restart.

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
dotnet run --project tests\client-registration    # 19 checks, no ArcGIS Pro needed
python -m pytest tests\                           # catalog drift, mock end-to-end
```

`client-registration` exercises the AI-client config writing against **copies**
in a temp folder, never a real config. What it checks is that registering and
unregistering leaves everything else in the file byte for byte — particularly
Codex's `config.toml`, which is edited as text rather than through a parser.

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

```powershell
.\scripts\build.ps1 -Sign
gh release create v0.2.0 `
    dist\ArcGISProMCP.esriAddinX `
    dist\Install-ArcGISProMCP.ps1 `
    --title "v0.2.0" --notes-file NOTES.md
```

**CI cannot build this.** GitHub Actions has no ArcGIS Pro to reference, so
releases are built on a machine that has it and uploaded by hand. CI can still
run `tests/client-registration` and the Python tests, neither of which needs
Pro.

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
