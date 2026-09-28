"""Synthetic privacy/export regression tests. Never read real credentials."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('publication', ROOT / 'scripts' / 'prepare_publication.py')
publication = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publication)


def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)


def icon(extra=b''):
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 16, 16, 8, 6, 0, 0, 0))
            + extra + chunk(b'IDAT', zlib.compress((b'\0' + b'\0' * 64) * 16)) + chunk(b'IEND', b''))


class PublicationTests(unittest.TestCase):
    def test_private_values_redacted(self):
        # Assemble synthetic values so the source itself remains publication-safe.
        samples = {
            'user-profile-path': 'C:' + '\\Users\\' + 'ExamplePerson\\file.txt',
            'windows-account-sid': 'S-1-5-' + '21-111-222-333-1001',
            'email-address': 'example-person' + '@' + 'example.invalid',
            'private-key': '-----BEGIN ' + 'PRIVATE KEY-----',
            'provider-credential': 'gh' + 'p_' + 'A' * 36,
            'url-credentials': 'https://' + 'synthetic:example' + '@' + 'example.invalid',
            'jwt': 'ey' + 'J' + 'x' * 20 + '.' + 'y' * 20 + '.' + 'z' * 20,
            'literal-bearer': 'Bearer ' + 'x' * 32,
            'literal-secret': 'token = "' + 'x' * 32 + '"',
            'unc-host-path': '\\' * 2 + 'example-host' + '\\share',
            'private-network-address': '.'.join(['192', '168', '22', '33']),
            'mac-address': ':'.join(['ab', 'cd', 'ef', '01', '23', '45']),
            'local-private-identifier': 'synthetic-private-identifier',
        }
        for category, sample in samples.items():
            with self.subTest(category=category):
                findings = publication.scan_text(sample, ['synthetic-private-identifier'])
                self.assertIn(category, [f['category'] for f in findings])
                self.assertNotIn(sample, json.dumps(findings))

    def test_benign_public_attribution(self):
        self.assertEqual([], publication.scan_text('Copyright upstream author; https://github.com/project/source; 127.0.0.1', []))

    def test_icon_metadata_and_trailing_data_denied(self):
        publication.validate_icon(icon())
        for unsafe in (icon(chunk(b'tEXt', b'Author\0ExamplePerson')), icon() + b'extra',
                       icon(chunk(b'pHYs', b'unknown'))):
            with self.assertRaises(ValueError):
                publication.validate_icon(unsafe)

    def test_exclusions_apply_even_when_tracked(self):
        for name in ('dist/ArcGISProMCP.esriAddinX', 'dist/Install-ArcGISProMCP.cmd',
                     '.git/config', 'artifacts/test.aprx', 'docs/images/demo.gif',
                     'tests/obj/cache.json', '.github/FUNDING.yml', 'docs/private.gdb/data'):
            self.assertTrue(publication.excluded(name), name)

    def test_unknown_binary_and_private_text_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'scripts').mkdir()
            (root / 'scripts' / 'payload.exe').write_bytes(b'MZfake')
            (root / 'README.md').write_text('synthetic-private-identifier', encoding='utf-8')
            report, payload = publication.audit(root, ['README.md', 'scripts/payload.exe'], ['synthetic-private-identifier'])
            self.assertEqual('fail', report['status'])
            self.assertEqual(2, len(report['findings']))
            with self.assertRaises(ValueError):
                publication.export(root, payload, report)

    def test_traversal_denied(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ('../README.md', '/README.md', 'C:/README.md', 'scripts\\file.py'):
                with self.assertRaises(ValueError):
                    publication.check_path(Path(folder), name)

    def test_symlink_denied(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'NOTICE').write_text('upstream attribution', encoding='utf-8')
            try:
                (root / 'README.md').symlink_to(root / 'NOTICE')
            except OSError:
                self.skipTest('OS does not permit test symlink creation')
            report, _ = publication.audit(root, ['README.md'], [])
            self.assertEqual('fail', report['status'])
            self.assertEqual('link-or-reparse-point', report['findings'][0]['category'])

    def test_export_manifest_and_metadata_deterministic(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'README.md').write_text('synthetic public source\n', encoding='utf-8')
            report, payload = publication.audit(root, ['README.md', '.git/config', 'docs/images/demo.gif'], [])
            self.assertEqual('pass', report['status'])
            first = publication.export(root, payload, report)
            second = publication.export(root, payload, report)
            self.assertNotEqual(first, second)
            self.assertEqual((first / 'ArcGIS-Pro-MCP-source.zip').read_bytes(),
                             (second / 'ArcGIS-Pro-MCP-source.zip').read_bytes())
            manifest = json.loads((first / 'source-manifest.json').read_text())
            with zipfile.ZipFile(first / 'ArcGIS-Pro-MCP-source.zip') as archive:
                self.assertEqual(['README.md'], archive.namelist())
                self.assertEqual(manifest['README.md'], hashlib.sha256(archive.read('README.md')).hexdigest())
                entry = archive.infolist()[0]
                self.assertEqual((1980, 1, 1, 0, 0, 0), entry.date_time)
                self.assertEqual(b'', entry.extra)
                self.assertEqual(b'', entry.comment)
            self.assertNotIn(str(root), (first / 'publication-audit.json').read_text())


if __name__ == '__main__':
    unittest.main()
