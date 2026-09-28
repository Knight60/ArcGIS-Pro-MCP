# Historical installation smoke test

This record describes the initial, pre-hardening 1.1.1 candidate, not the current
security profile. See [the 1.1.2 review](security-review-2026-09-28.md) for current
test results, restrictions, and known limits.

The initial candidate was built and smoke-tested on ArcGIS Pro 3.7 with .NET 10
using a disposable project and three synthetic points. Tests covered bridge
discovery, basic map/data operations, and a local Ollama tool-call round trip.
They did not validate all 112 upstream tools or establish security certification.

No existing GIS data was used. Local projects, screenshots, configuration backups,
installation paths, and account details are intentionally not publication assets.
The obsolete installer test is retired. Use `scripts/test-hardened-installed.ps1`
with the documented synthetic fixture for the current read-only acceptance test.
