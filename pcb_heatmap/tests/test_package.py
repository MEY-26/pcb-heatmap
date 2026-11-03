"""Portable release checks: no KiCad, GUI, user board or network is required."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[2]
BUILDER = next(path for path in (ROOT / 'heatmap_tools' / 'build_package.py',
                                ROOT / 'build_pcm.py', ROOT / 'build_package.py')
               if path.is_file())
spec = importlib.util.spec_from_file_location('heatmap_package_builder', BUILDER)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pcb-heatmap-package-test-')
        self.root = Path(self.temp.name) / 'source'
        self.source = self.root / 'pcb_heatmap'
        self.source.mkdir(parents=True)
        for name in (*builder.FILES, 'pcm-icon.png'):
            shutil.copy2(ROOT / 'pcb_heatmap' / name, self.source / name)
        self.metadata = builder.metadata_template()

    def tearDown(self):
        self.temp.cleanup()

    def metadata_file(self, metadata=None):
        (self.root / 'metadata.json').write_text(
            json.dumps(self.metadata if metadata is None else metadata), encoding='utf-8')

    def build(self, name='out'):
        return builder.build(self.root, Path(self.temp.name) / name)

    def test_archive_payload_metadata_checksums_and_submission_match(self):
        self.metadata_file()
        package = self.build()
        with zipfile.ZipFile(package) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(set(archive.namelist()),
                             {'plugins/' + name for name in builder.FILES}
                             | {'resources/icon.png', 'metadata.json'})
            metadata = json.loads(archive.read('metadata.json'))
            self.assertEqual(metadata, self.metadata)
            self.assertEqual(len(metadata['versions']), 1)
            self.assertFalse(any(k.startswith('download_') for k in metadata['versions'][0]))
            self.assertEqual(metadata['author']['contact']['web'], 'https://github.com/MEY-26')
            self.assertEqual(metadata['versions'][0]['runtime'], 'swig')
            self.assertEqual(metadata['versions'][0]['platforms'], ['windows'])
            self.assertEqual(struct.unpack('>II', archive.read('resources/icon.png')[16:24]), (64, 64))
            install_size = sum(info.file_size for info in archive.infolist())
        directory = package.parent / 'submission/packages' / builder.IDENTIFIER
        submission = json.loads((directory / 'metadata.json').read_text(encoding='utf-8'))
        entry = submission['versions'][0]
        digest = hashlib.sha256(package.read_bytes()).hexdigest()
        self.assertEqual(entry['download_sha256'], digest)
        self.assertEqual(entry['download_size'], package.stat().st_size)
        self.assertEqual(entry['install_size'], install_size)
        self.assertEqual(entry['download_url'],
                         'https://github.com/MEY-26/pcb-heatmap/releases/download/v0.3.4/' + package.name)
        self.assertEqual((directory / 'icon.png').read_bytes(), (self.source / 'pcm-icon.png').read_bytes())
        self.assertEqual((package.parent / 'SHA256SUMS.txt').read_text(), digest + '  ' + package.name + '\n')

    def test_reproducibility_ignores_source_timestamps_and_repeated_build_is_safe(self):
        first = self.build('first')
        for path in self.source.iterdir():
            os.utime(path, (1577836800, 1577836800))
        second = self.build('second')
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(builder.build(self.root, first.parent), first)

    def test_existing_different_archive_is_not_replaced(self):
        package = self.build()
        original = package.read_bytes()
        (self.source / 'README.md').write_text('Changed unpublished notes', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.build()
        self.assertEqual(package.read_bytes(), original)

    def test_code_versions_and_archive_version_must_agree(self):
        path = self.source / 'model.py'
        path.write_text(path.read_text(encoding='utf-8').replace("VERSION = '0.3.4'", "VERSION = '9.9.9'"), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'versions differ'):
            self.build()
        shutil.copy2(ROOT / 'pcb_heatmap/model.py', path)
        metadata = deepcopy(self.metadata)
        metadata['versions'][0]['version'] = '9.9.9'
        self.metadata_file(metadata)
        with self.assertRaisesRegex(ValueError, 'exactly the code version'):
            self.build()

    def test_archive_download_fields_and_missing_required_metadata_are_rejected(self):
        variants = []
        metadata = deepcopy(self.metadata)
        metadata['versions'][0]['download_url'] = 'https://example.invalid/file.zip'
        variants.append(metadata)
        metadata = deepcopy(self.metadata)
        del metadata['author']['contact']
        variants.append(metadata)
        metadata = deepcopy(self.metadata)
        del metadata['resources']
        variants.append(metadata)
        for index, metadata in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.metadata_file(metadata)
                self.build(str(index))

    def test_all_three_icons_are_required_and_have_exact_dimensions(self):
        for index, name in enumerate(('toolbar-24.png', 'toolbar-48.png', 'pcm-icon.png')):
            path = self.source / name
            raw = path.read_bytes()
            with self.subTest(icon=name):
                path.unlink()
                with self.assertRaisesRegex(ValueError, 'Missing package files'):
                    self.build('missing-' + str(index))
                wrong = bytearray(raw)
                wrong[16:20] = struct.pack('>I', 17)
                path.write_bytes(wrong)
                with self.assertRaisesRegex(ValueError, 'PNG'):
                    self.build('bad-size-' + str(index))
                path.write_bytes(raw)

    def test_whitelist_excludes_user_designs_results_caches_and_local_paths(self):
        for name in ('private.kicad_pcb', 'private.kicad_sch', 'result.npz', 'scenario.json'):
            (self.source / name).write_text('MUST NOT BE PUBLISHED', encoding='utf-8')
        (self.source / '__pycache__').mkdir()
        (self.source / '__pycache__/private.pyc').write_bytes(b'PRIVATE CACHE')
        package = self.build()
        with zipfile.ZipFile(package) as archive:
            self.assertFalse(any(n.endswith(('.kicad_pcb', '.kicad_sch', '.npz', '.pyc'))
                                 or '__pycache__' in n or n.endswith('scenario.json')
                                 for n in archive.namelist()))
            self.assertNotIn(str(self.root).encode(), archive.read('metadata.json'))

    def test_public_root_metadata_is_used_and_unverified_runtime_is_rejected(self):
        self.metadata['description'] = 'Synthetic custom release description'
        self.metadata_file()
        with zipfile.ZipFile(self.build()) as archive:
            self.assertEqual(json.loads(archive.read('metadata.json'))['description'], self.metadata['description'])
        for index, update in enumerate(({'runtime': 'ipc'}, {'platforms': ['linux']}, {'kicad_version_max': '11.0'})):
            metadata = deepcopy(self.metadata)
            metadata['versions'][0].update(update)
            self.metadata_file(metadata)
            with self.subTest(update=update), self.assertRaisesRegex(ValueError, 'Windows / KiCad'):
                self.build('runtime-' + str(index))


if __name__ == '__main__':
    unittest.main()
