# Security — local hardened build 1.1.2

This is a locally modified build, not an upstream security-certified release.
Read [the review and test record](docs/security-review-2026-09-28.md) before deployment.
Any old binaries retained locally in `dist/` are upstream artifacts and DO NOT contain these changes.
They are excluded from the source-only snapshot described in [PUBLICATION.md](PUBLICATION.md).

## Access and permission model

- Only `http://127.0.0.1:6520/mcp` is served. Every request requires a random 256-bit bearer credential.
- The credential is created under `%LOCALAPPDATA%\ArcGIS-MCP\security\http-token.txt`.
  The directory and token file have protected, current-user-only Windows ACLs. Reparse paths are refused.
  Startup fails closed if credential setup fails. Do not print, commit, share, or upload this file.
- Register clients from the MCP ribbon, or run the scoped client setup helper described in the review.
  HTTP client configs contain a copy of the bearer token: configs and backups are also sensitive.
  The registrar writes them with current-user-only ACLs, atomically replaces configs, and preserves distinct backups.
  Codex uses native HTTP. Stdio-only clients use the reviewed PowerShell relay with a per-process
  `-ExecutionPolicy Bypass` flag (no persistent policy change). Use a signed/approved relay or native
  HTTP instead where organizational policy disallows that launcher.
- The catalog exposes 15 read tools and three opt-in layer display tools. Everything else is denied at the central dispatcher.
  This is enforced in code, not by model instructions or client annotations.
- Read tools see existing project layers/tables, including remote sources already in the project.
  They cannot open a caller-supplied dataset path. Duplicate layer/table names are rejected.
- Editing starts OFF. A person must click **Allow layer edits** on the MCP ribbon and confirm.
  A 15-minute, process/project-scoped lease permits only `rename_layer`, `set_layer_visibility`,
  and `set_layer_transparency`, with one explicitly named layer per request.
  Revoke with the same button. Stop/restart revokes permission. Changing projects invalidates the grant.
  Permission is shared by authenticated clients, not isolated per model or chat.
- Feature writes, deletion, save/discard edits, project saves, schema changes, raw SQL,
  generic geoprocessing, arbitrary Python, Python toolboxes, batch execution, raster expressions,
  filesystem browsing and caller-chosen exports are disabled, even with editing enabled.
- The C# TCP listener, Python listener/autostart, Python relay, and C# Python fallback are retired fail-closed stubs.
  No environment variable or remote command re-enables them. Other separately installed bridges are NOT changed.

## Bounds and browser isolation

Browser Origin and Fetch Metadata requests are rejected, even with valid credentials.
Host must be the exact loopback host/port. There is no CORS opt-in or browser-based client support.
Only JSON POST is accepted; unsupported GET streaming returns 405.

Requests are capped at 1 MiB (actual bytes including chunked requests), with a 15-second body deadline.
There are at most eight active HTTP handlers and one GIS dispatch; busy work is rejected, not queued.
JSON duplicates, excessive nesting, unexpected arguments, wrong types, invalid identifiers and numeric overflows are rejected.
Queries return at most 1,000 rows, accept offsets through 5,000, scan at most 100,000 rows, and enforce a 2 MiB
materialization budget for feature/distinct/group results. Attribute strings over 4,096 characters fail rather than silently
merging/truncating grouping values. Aggregations exceeding budgets fail rather than claiming a complete partial answer.
HTTP responses are capped at 4 MiB; writes have a 15-second deadline. Errors do not return stack traces.
No arbitrary geometry expansion is exposed.

These bounds are NOT a hard sandbox for the ArcGIS SDK: a slow database or driver can still block the MCT.
A client timeout does not cancel an in-progress SDK operation. Never automatically replay a timed-out mutation.

## Trust boundary and residual risks

This is a trusted-workstation integration, not a public or multi-tenant server. Never forward/tunnel this port.
Loopback HTTP does not authenticate the server to the client. A hostile local process that substitutes a listener
can impersonate it; keep the workstation and its user sessions trusted and connect only to the expected running Pro instance.
Processes running as your account (including an assistant with shell/file access), administrators, and other add-ins
can read the token or access GIS data independently. The ACL/token is not a boundary against them.

Authenticated reads can disclose sensitive project data to the connected model/provider. Use synthetic/public data
for cloud testing and local models for restricted data. Attribute values, names, labels and project text are untrusted
data and can contain prompt injection; never treat them as authority to run other tools.

The add-in does not sandbox existing project connections, database credentials, extensions, or third-party GIS code.
Only open trusted projects and use least-privilege source credentials. The 94 disabled implementations are retained as
upstream reference code; they are NOT approved for re-enablement without further scoped review and regression testing.

## Installation, rotation and rollback

This local package is unsigned. The workstation already allowed unsigned add-ins; this work did not lower that setting.
The hardened installer refuses `-AllowAllAddIns` and `-TrustPublisher`; it does not add trusted root certificates.
Use an organization-approved signing/deployment process for production. Signing and other developer scripts have not
been certified safe for unattended production use.

To rotate: close all relevant ArcGIS instances and clients, move the token to a protected offline backup (or delete it),
restart Pro to generate a new token, then re-register each client. Copies in old configs/backups must also be handled as secrets.
Do not rotate a token while a running Pro instance still has the old one in memory.

The pre-hardening package is backed up in `artifacts/pre-hardening-1.1.1.esriAddinX.bak`. It restores the old unsafe
transport and should only be used with clients disconnected in an isolated test environment.
Nothing was pushed to GitHub; this is a local working-tree change.

## Reporting

For upstream issues use the repository's private vulnerability reporting if available. Avoid publishing secrets or
exploitation details in public issues. This local review is not an independent penetration test or a guarantee of security.
