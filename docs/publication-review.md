# Publication privacy review

## Scope

The source-only working-copy snapshot was reviewed for local account and machine
identifiers, profile/UNC paths, credential patterns, private network addresses,
image metadata, Git metadata, and generated artifacts. Every included text file
and filename passes the publication scanner. Both JSON tool resources were included
in that scan. All 16 retained 16/32-pixel application icons were visually inspected;
their PNG chunks contain only structural and fixed rendering information.

Removed profile paths and unnecessary account/session details from test reports;
labelled obsolete validation evidence as historical. Removed screenshot references,
redirected capture defaults into ignored artifacts, and stopped client-registration
tests from printing real configuration, launcher, and temporary profile paths.

Compiled add-ins, self-contained installers, old build reports, screenshots/demo
images, and the upstream funding configuration are excluded even if tracked.
Git history, author/committer identities, remotes, ignored caches, local GIS data,
credentials, and configuration backups are not exported. Original local files
are retained. Required upstream license/copyright notices and public provenance
are intentionally preserved. The export command does not publish anything by itself.
For the subsequently authorized fork contribution, upstream's existing public history
is retained; only the audited source tree and a public no-reply commit identity are added.

## Verification

- Python suite: 16 passed; one filesystem symlink test skipped because the test
  account could not create symlinks. Path traversal, unknown binaries, sensitive
  text, image metadata, exclusion rules, manifest hashes, and deterministic ZIP
  metadata have passing regression coverage.
- .NET 10 client-registration tests: passed, using fake credentials/temp configs.
- .NET 10 HTTP/security tests: passed with fake GIS handlers on an isolated
  loopback test port. The sandbox could not start HttpListener, so this test was
  rerun outside the sandbox. The installed bridge and real GIS data were not used.
- PowerShell installer/script-integrity validation and Git whitespace checks passed.
- A bounded local Ollama secondary review received only the exporter source.
  Its suggested defects were not supported by inspection and were not adopted.

The generated audit/manifest supplies the exact final file count and hashes.
No runtime code was changed for this publication pass beyond synthetic test data.
The installed hardened add-in does not need reinstalling for these documentation,
test-output, and publication-tooling changes.

## Limits and next step

This is a source privacy audit, not independent penetration testing or a guarantee
that no possible identifying information exists. Pattern scans cannot recognize
every name, credential format, or covert data encoding. Private local artifacts
were excluded, not made safe to publish. Compiled releases and any later additions
require their own review. Follow [PUBLICATION.md](../PUBLICATION.md): upload only
the extracted source snapshot with a chosen public no-reply commit identity, never
the private working directory. The documented fork mode retains public upstream
history for a reviewable pull request; the standalone mode is history-free.
