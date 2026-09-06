# Security

## What this add-in exposes

While ArcGIS Pro is open and the bridge is running, the add-in listens on
**loopback only**:

| Port | What answers |
|---|---|
| `127.0.0.1:6520` | MCP over HTTP — the endpoint AI clients connect to |
| `127.0.0.1:6510` | the TCP bridge |
| `127.0.0.1:6511` | the in-Pro Python fallback, for `execute_arcpy_code` |

Nothing binds a routable address, and nothing is reachable from another
machine. There is no authentication: anything that can open a loopback socket
on your computer can drive ArcGIS Pro through it, with your permissions.

Treat it as you would a terminal left open. In particular:

- Anything reachable from the add-in is reachable by the assistant you connect
  — every dataset, every geodatabase connection, every network share the
  project can see.
- `execute_arcpy_code` and `run_geoprocessing_tool` run arbitrary code inside
  ArcGIS Pro. That is the point of them, and it is also the whole risk.
- Stop the bridge from the ribbon when you are not using it. Closing ArcGIS Pro
  stops it too.

## Add-in signing

Releases are signed with a self-signed certificate. That certificate is not
trusted on any machine but the one that created it, so on a machine with
ArcGIS Pro's add-in security turned on you have to decide, explicitly, to trust
it — the installer says so and offers the two ways forward. Do not turn add-in
security off to make an add-in load unless you are willing to load any add-in.

Verify what you install: `dist/build-report.json` carries the SHA-256 of both
the package and the installer, and `scripts/build.ps1` checks that the payload
embedded in the installer hashes to the same value as the package beside it.

## Reporting a vulnerability

Open a [GitHub issue](https://github.com/Knight60/ArcGIS-Pro-MCP/issues) for
anything already public. For something that should not be public yet, use
GitHub's private vulnerability reporting on the repository's Security tab.

Please include the add-in version (the ribbon's Status button reports it), the
ArcGIS Pro version, and what an attacker would be able to do. A reply should
not take more than a few days; this is a one-person project, so please allow
for that.

## Supported versions

The latest release is the supported one. Fixes go into a new release rather
than being backported.
