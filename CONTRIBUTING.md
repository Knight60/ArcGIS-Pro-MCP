# Contributing

Bug reports, fixes and new commands are all welcome. This page is the short
version; [BUILD.md](BUILD.md) has the detail on building, testing and
releasing.

## Before you start

You need **ArcGIS Pro 3.7** to build the add-in — its assemblies are referenced
straight out of the installation. You do not need the ArcGIS Pro SDK, Visual
Studio, or a NuGet feed. See
[BUILD.md](BUILD.md#the-net-version-has-to-match-arcgis-pro).

The tests under `tests/` need neither ArcGIS Pro nor Python-with-Pro, and CI
runs them on every push.

## Reporting a bug

Include the add-in version (the Status button on the MCP tab reports it), the
ArcGIS Pro version, which AI client you were using, and what you asked it to
do. If a tool call failed, the assistant's transcript of the error is more
useful than a description of it.

## Adding a command

1. Define it in `src/arcgis_pro_mcp/catalog.py` — the single source of truth
   for all 112 tools.
2. Write the handler under `addin/ArcGISProMCP/Commands/`, grouped by subject,
   and register it with `CommandRouter.Register`.
3. `.\scripts\build.ps1`

`tests/test_catalog_matches_bridge.py` fails if the catalog and the handlers
disagree in either direction, so a command cannot be half-added.

Two things that will bite you, both documented in
[docs/addin.md](docs/addin.md):

- Only the **Main CIM Thread** may touch the open project. Use
  `QueuedTask.Run`. A few operations — saving, and creating panes — belong to
  the WPF UI thread instead.
- `CommandRouter.Register` is for the MCT; `RegisterAsync` is for handlers that
  await. Awaiting inside `QueuedTask.Run` deadlocks.

## Adding an AI client

Add it to `McpClientCatalog.All` in `addin/ArcGISProMCP/Clients/McpClients.cs`,
a button to `Config.daml` and `UI/Buttons.cs`, and a case to
`tests/client-registration`.

Find out what shape the client's config actually takes, from its own
documentation or its binary, and say in a comment how you know. A config
written in the wrong shape does not fail — it is **ignored**, and the button
goes green while nothing works. That mistake has already cost this project one
release.

## Style

- `.editorconfig` covers indentation and line endings; `.gitattributes` keeps
  line endings consistent whatever your `core.autocrlf` says.
- Comments should say **why**, not restate the code. The existing comments are
  the standard to match.
- Every behavioural change needs a test that fails without it. If the change
  cannot be tested without ArcGIS Pro, say so in the pull request and describe
  what you ran by hand.

## Licence

Contributions are accepted under [AGPL-3.0-or-later](LICENSE), the licence of
the project. Note that the maintainer also offers the code under a separate
[commercial licence](COMMERCIAL-LICENSE.md); by opening a pull request you
agree that your contribution may be included in both.
