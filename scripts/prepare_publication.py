"""Audit and export source without history, build products, or local account data.

Standard library only. No network, credential access, Git mutation, or upload.
See PUBLICATION.md for scope and limits; a clean scan is not a security guarantee.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import stat
import struct
import subprocess
import tempfile
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
TOP_FILES = {
    '.editorconfig', '.gitattributes', '.gitignore', '.mcp.json', 'BUILD.md',
    'CHANGELOG.md', 'COMMERCIAL-LICENSE.md', 'CONTRIBUTING.md', 'LICENSE',
    'NOTICE', 'README.md', 'SECURITY.md', 'PUBLICATION.md', 'pyproject.toml',
}
SOURCE_DIRS = {'.github', 'addin', 'arcgis_pro_plugin', 'docs', 'scripts', 'src', 'tests'}
TEXT_SUFFIXES = {'.md', '.cs', '.csproj', '.daml', '.json', '.py', '.ps1', '.pyt', '.toml', '.yml', '.yaml'}
PRIVATE_DIRS = {'.git', '.codex', '.agents', 'artifacts', 'bin', 'obj', 'build',
                '__pycache__', '.pytest_cache', '.venv', 'venv', 'node_modules'}
EXCLUDED_FILES = {
    '.github/FUNDING.yml',
    'dist/ArcGISProMCP.esriAddinX', 'dist/Install-ArcGISProMCP.cmd',
    'dist/build-report.json',
}
PATTERNS = {
    'user-profile-path': re.compile(r'(?i)(?:[a-z]:[/\\]+Users[/\\]+\w[^/\\\s\"\']*|/(?:home|Users)/\w[^/\s]*)'),
    'windows-account-sid': re.compile(r'S-1-5-21-\d+-\d+-\d+(?:-\d+)?', re.I),
    'email-address': re.compile(r'(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b'),
    'private-key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
    'provider-credential': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-(?:proj-)?[A-Za-z0-9_-]{24,}|AKIA[A-Z0-9]{16})\b'),
    'url-credentials': re.compile(r'(?i)https?://[^/\s:@]+:[^/\s@]+@'),
    'jwt': re.compile(r'\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\b'),
    'literal-bearer': re.compile(r'(?i)\bBearer\s+[A-Za-z0-9_.-]{24,}'),
    'literal-secret': re.compile(r'''(?ix)\b(?:api[_-]?key|password|secret|token|credential|authorization|access[_-]?token|auth[_-]?token)\b["']?\s*[:=]\s*["'][A-Za-z0-9_+/=.~-]{24,}["']'''),
    'unc-host-path': re.compile(r'\\\\[A-Za-z0-9][A-Za-z0-9.-]+\\[A-Za-z0-9$]'),
    'private-network-address': re.compile(r'\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b'),
    'mac-address': re.compile(r'(?i)(?<![0-9a-f:.-])(?:[0-9a-f]{2}:){5}[0-9a-f]{2}(?![0-9a-f:.-])'),
}


def excluded(name: str) -> bool:
    parts = PurePosixPath(name).parts
    return (name in EXCLUDED_FILES or name.startswith('docs/images/')
            or any(p.casefold() in PRIVATE_DIRS or p.lower().endswith('.gdb') for p in parts))


def check_path(root: Path, name: str) -> Path:
    relative = PurePosixPath(name)
    if (relative.is_absolute() or '..' in relative.parts or '\\' in name
            or ':' in name or not relative.parts):
        raise ValueError('unsafe-relative-path')
    current = root
    for part in relative.parts:
        current = current / part
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('link-or-reparse-point')
    if not current.is_file() or not current.resolve().is_relative_to(root.resolve()):
        raise ValueError('not-a-contained-regular-file')
    return current


def validate_icon(data: bytes) -> None:
    if not data.startswith(b'\x89PNG\r\n\x1a\n') or len(data) > 16384:
        raise ValueError('invalid-icon')
    offset, kinds = 8, []
    while offset + 12 <= len(data):
        length = struct.unpack('>I', data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        end = offset + 12 + length
        rendering = {b'sRGB': bytes.fromhex('00'), b'gAMA': bytes.fromhex('0000B18F'),
                     b'pHYs': bytes.fromhex('00000EC300000EC301')}
        if end > len(data) or kind not in {b'IHDR', b'IDAT', b'IEND', *rendering}:
            raise ValueError('icon-metadata-or-unknown-chunk')
        if kind in rendering and data[offset + 8:end - 4] != rendering[kind]:
            raise ValueError('unapproved-icon-rendering-metadata')
        chunk = data[offset + 4:offset + 8 + length]
        if zlib.crc32(chunk) & 0xffffffff != struct.unpack('>I', data[end - 4:end])[0]:
            raise ValueError('icon-crc')
        if kind == b'IHDR':
            if length != 13 or kinds:
                raise ValueError('icon-header')
            width, height = struct.unpack('>II', data[offset + 8:offset + 16])
            if width not in (16, 32) or height != width:
                raise ValueError('icon-dimensions')
        kinds.append(kind)
        offset = end
        if kind == b'IEND':
            if length or offset != len(data):
                raise ValueError('icon-trailing-data')
            break
    if not kinds or kinds[0] != b'IHDR' or kinds[-1] != b'IEND' or b'IDAT' not in kinds:
        raise ValueError('icon-structure')


def scan_text(text: str, terms: list[str]) -> list[dict]:
    findings = []
    for number, line in enumerate(text.splitlines(), 1):
        for category, pattern in PATTERNS.items():
            if pattern.search(line):
                findings.append({'line': number, 'category': category})
        if any(term.casefold() in line.casefold() for term in terms if len(term) >= 3):
            findings.append({'line': number, 'category': 'local-private-identifier'})
    return findings


def private_terms(root: Path) -> list[str]:
    terms = {os.environ.get('USERNAME', ''), os.environ.get('COMPUTERNAME', ''), socket.gethostname()}
    # Also covers a sandbox account inspecting a different user's source tree.
    for match in re.finditer(r'(?i)(?:[a-z]:/Users/|/home/|/Users/)([^/]+)', root.as_posix()):
        terms.add(match.group(1))
    return sorted(t for t in terms if len(t) >= 3)


def audit(root: Path, names: list[str], terms: list[str]) -> tuple[dict, dict[str, bytes]]:
    findings, payload, omitted = [], {}, 0
    for name in sorted(set(names)):
        if excluded(name):
            omitted += 1
            continue
        # Never print matching strings or potentially private filenames in failures.
        file_findings = scan_text(name, terms)
        try:
            path = check_path(root, name)
            top = PurePosixPath(name).parts[0]
            if name not in TOP_FILES and top not in SOURCE_DIRS and name != 'dist/HARDENING-NOTICE.md':
                raise ValueError('unapproved-source-location')
            if path.stat().st_size > 2 * 1024 * 1024:
                raise ValueError('oversized-source-file')
            data = path.read_bytes()
            if name.startswith('addin/ArcGISProMCP/Images/') and path.suffix == '.png':
                validate_icon(data)
            else:
                if name not in TOP_FILES and path.suffix not in TEXT_SUFFIXES:
                    raise ValueError('unapproved-file-type')
                decoded = data.decode('utf-8-sig')
                if '\0' in decoded:
                    raise ValueError('binary-in-text-file')
                file_findings.extend(scan_text(decoded, terms))
            payload[name] = data
        except (ValueError, OSError, UnicodeError) as error:
            category = str(error) if isinstance(error, ValueError) and not isinstance(error, UnicodeError) else type(error).__name__
            file_findings.append({'line': 0, 'category': category})
        if file_findings:
            label = name if not scan_text(name, terms) else '[redacted filename]'
            findings.extend({'file': label, **finding} for finding in file_findings)
    report = {'status': 'pass' if not findings else 'fail',
              'included_files': len(payload), 'excluded_candidate_files': omitted,
              'scope': 'Git tracked and non-ignored untracked working files; no Git history or ignored runtime artifacts',
              'findings': findings,
              'limitations': 'Pattern scan, not proof of absence; public upstream attribution retained; binary releases excluded.'}
    return report, payload


def export(root: Path, payload: dict[str, bytes], report: dict) -> Path:
    if report['status'] != 'pass' or not payload:
        raise ValueError('refusing-failed-or-empty-export')
    destination = root / 'artifacts' / 'github-ready'
    # Validate each existing ancestor; do not follow a junction to another location.
    for folder in (root / 'artifacts', destination):
        if folder.exists() or folder.is_symlink():
            if folder.is_symlink() or getattr(folder.lstat(), 'st_file_attributes', 0) & 0x400:
                raise ValueError('output-link-or-reparse-point')
        else:
            folder.mkdir()
    output = Path(tempfile.mkdtemp(prefix='source-', dir=destination))
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(payload.items())}
    with zipfile.ZipFile(output / 'ArcGIS-Pro-MCP-source.zip', 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(payload.items()):
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = (stat.S_IFREG | 0o644) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, data)
    (output / 'source-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    report = {**report, 'archive_sha256': hashlib.sha256((output / 'ArcGIS-Pro-MCP-source.zip').read_bytes()).hexdigest()}
    (output / 'publication-audit.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='audit without generating artifacts')
    parser.add_argument('--private-term', action='append', default=[], help='additional private identifier; never stored in report')
    args = parser.parse_args()
    result = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
                            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    names = [n for n in result.stdout.decode('utf-8').split('\0') if n]
    report, payload = audit(ROOT, names, private_terms(ROOT) + args.private_term)
    print(json.dumps(report, indent=2))
    if report['status'] != 'pass':
        return 1
    if not args.check:
        print('Created: ' + export(ROOT, payload, report).relative_to(ROOT).as_posix())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
