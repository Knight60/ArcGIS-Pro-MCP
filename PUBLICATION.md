# Source-only publication

Use the output of `python scripts/prepare_publication.py` as the source payload,
not this working directory or its private artifacts. Nothing in that command pushes to GitHub.
It audits the current tracked and untracked, non-ignored source files; fails on
unexpected file types, links, suspicious private content, or image metadata; and
creates a new source ZIP plus a relative-path SHA-256 inventory under ignored
`artifacts/github-ready/`. It never overwrites an existing export.

## Included and excluded

Include source, tests, documentation, licenses, public upstream attribution, and
the small application icons. Preserve upstream copyrights and license notices;
public author names/project links are intentional attribution, not local account
data. Esri product/API identifiers, application GUIDs, public package identifiers,
loopback addresses, and explicitly synthetic test values are not host identities.

Exclude `.git` and all author/committer/remote history, caches, build outputs,
logs, credentials/config backups, screenshots, animated demonstrations, local GIS
projects/data, compiled add-ins, embedded-binary installers, and old build reports.
The upstream sponsorship configuration is not copied into the new source snapshot.
These excluded files remain locally; exclusion does not delete private GIS data or
rewrite upstream history. `.gitignore` alone cannot remove already-tracked files.

Every included text file and filename is scanned. Icons are restricted to the
reviewed application image directory, at most 32 by 32 pixels, with only structural
PNG chunks and fixed sRGB/gamma/resolution values (no text/EXIF/profile metadata).
ZIP entry timestamps and permissions
are fixed; no absolute source paths, usernames, machine names, or Git metadata are
written into the manifest. Findings report categories, not matching secret values.

The scanner also checks current environment/profile identifiers. To check additional
private names without adding them to the repository, supply repeatable
`--private-term` arguments locally. Do not put those arguments into shared logs or CI.
Pattern scanning is not a proof of absence: arbitrary natural-language identifiers,
novel credential formats, data embedded in pixels, and third-party vulnerabilities
still require human review. The original guide is historical; the current supported
security profile is in [SECURITY.md](SECURITY.md) and the
[review/test record](docs/security-review-2026-09-28.md).

## Upload process

1. Run tests, then `python scripts/prepare_publication.py --check` and the export.
2. Inspect `publication-audit.json`, `source-manifest.json`, and the ZIP inventory.
   Keep only files listed in the manifest; do not add local logs or configuration.
3. Choose the publication mode explicitly:
   - For a history-free standalone repository, extract the ZIP to a fresh directory
     and initialize a new repository. Do not copy the original local `.git`.
   - For an upstream contribution, create a public GitHub fork and a dedicated
     branch based on a verified public upstream commit. Use only the audited ZIP
     as the new source tree. A fork necessarily retains upstream's already-public
     history, identities, and historical assets; the ZIP exclusion policy does not
     erase that history. Never import private local commits or configuration.
4. Use a chosen public display name and GitHub-provided no-reply author AND
   committer address. Inspect the outgoing commit and tree before pushing only the
   dedicated branch to the chosen fork. Do not force-push or update upstream/main.
5. Recheck any README links and repository description for the chosen destination.
   Keep upstream attribution clearly identified. Open a draft pull request when
   contributing upstream and report CI/manual acceptance gaps without claiming certification.

Compiled releases need a separate audit of PDB/source paths, assembly metadata,
signing-certificate identity, ZIP entries, and installer contents, plus renewed
runtime acceptance tests. No binary release is approved by this source audit.

For later revisions, rerun the audit before committing; new history can disclose
author names/emails even when file content is clean. If a credential was ever
published, removing it from a later commit is insufficient: revoke/rotate it and
address history and caches separately. No credential disclosure was found in this
source preparation, and runtime credentials were not included in the audit input.
