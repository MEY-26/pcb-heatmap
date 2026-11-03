"""Build a deterministic KiCad PCM archive and catalogue-submission files.

This builder never connects to a service or includes user designs/results.
It runs with the Python standard library, without loading KiCad or the plugin.
"""
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import struct
import zipfile


ROOT = Path(__file__).resolve().parent
if not (ROOT / 'pcb_heatmap').is_dir():
    ROOT = ROOT.parent
SOURCE = ROOT / 'pcb_heatmap'
VERSION = '0.3.4'
IDENTIFIER = 'com.github.mey-26.pcb-heatmap'
FILES = (
    '__init__.py', 'plugin.py', 'main.py', 'model.py', 'extractor.py', 'solver.py',
    'gui.py', 'visual_gui.py', 'board_view.py', 'layout_export.py', 'contacts.py',
    'snapshot.py', 'ui_controls.py', 'preferences.py', 'materials.py', 'i18n.py',
    'worker.py', 'toolbar-24.png', 'toolbar-48.png', 'icon.svg', 'README.md',
    'README.tr.md', 'LICENSE',
)


def metadata_template(version=VERSION):
    """Fallback for the private tree; public releases use root/metadata.json."""
    return {
        '$schema': 'https://go.kicad.org/pcm/schemas/v2',
        'name': 'PCB Heatmap',
        'description': 'Interactive multilayer DC current, voltage-drop and estimated board-temperature maps for KiCad 10. English/Turkish; local analysis.',
        'description_full': (
            'A free local analysis plugin for KiCad 10. Click directly on a saved PCB view '
            'to assign source/load pads, copper-point terminals and component heat. Includes '
            'zoom, pan, reference search, multi-pad groups and numerical overlays aligned '
            'with copper, filled zones and vias. The solver estimates steady DC distribution '
            'and coupled steady-state board temperature using isolated calculation workers. '
            'English/Turkish UI. No network, account, downloaded solver or paid service. '
            'NumPy and wxPython are supplied by KiCad on the tested Windows installation. '
            'Engineering preview: use mesh refinement and independent measurements. '
            'Results are not semiconductor junction temperatures, switching-waveform '
            'simulation or a validated operating-current rating.'),
        'identifier': IDENTIFIER,
        'type': 'plugin',
        'author': {'name': 'Mehmet Emin Yaman',
                   'contact': {'web': 'https://github.com/MEY-26'}},
        'license': 'MIT',
        'resources': {'homepage': 'https://github.com/MEY-26/pcb-heatmap',
                      'issues': 'https://github.com/MEY-26/pcb-heatmap/issues'},
        'tags': ['thermal', 'power-integrity', 'dc', 'heatmap'],
        'versions': [{'version': version, 'status': 'testing',
                      'kicad_version': '10.0', 'kicad_version_max': '10.0',
                      'runtime': 'swig', 'platforms': ['windows']}],
    }


def code_version(source):
    versions = []
    for name, variable in (('model.py', 'VERSION'), ('__init__.py', '__version__')):
        match = re.search(r'^' + re.escape(variable) + r'\s*=\s*[\'"]([^\'"]+)',
                          (source / name).read_text(encoding='utf-8'), re.M)
        if match is None:
            raise ValueError('Missing code version in ' + name)
        versions.append(match.group(1))
    if versions[0] != versions[1]:
        raise ValueError('Plugin code versions differ')
    return versions[0]


def check_metadata(metadata, version):
    if metadata.get('identifier') != IDENTIFIER:
        raise ValueError('Unexpected PCM identifier')
    author = metadata.get('author', {})
    if not author.get('name') or not author.get('contact'):
        raise ValueError('Metadata author.contact is required')
    if not metadata.get('resources', {}).get('homepage'):
        raise ValueError('Metadata resources.homepage is required')
    versions = metadata.get('versions', [])
    if len(versions) != 1 or versions[0].get('version') != version:
        raise ValueError('Archive metadata must contain exactly the code version')
    if any(key.startswith('download_') for entry in versions for key in entry):
        raise ValueError('Archive metadata must not contain download fields')
    entry = versions[0]
    if (entry.get('runtime') != 'swig' or entry.get('platforms') != ['windows']
            or entry.get('kicad_version') != '10.0'
            or entry.get('kicad_version_max') != '10.0'):
        raise ValueError('This release targets Windows / KiCad 10.0 / SWIG')


def check_png(path, size):
    data = path.read_bytes()
    if (len(data) < 24 or data[:8] != b'\x89PNG\r\n\x1a\n'
            or struct.unpack('>II', data[16:24]) != (size, size)):
        raise ValueError(f'{path.name} must be a {size}x{size} PNG')


def build(root=None, output=None):
    root = Path(root or ROOT).resolve()
    source = root / 'pcb_heatmap'
    missing = [name for name in (*FILES, 'pcm-icon.png') if not (source / name).is_file()]
    if missing:
        raise ValueError('Missing package files: ' + ', '.join(missing))
    version = code_version(source)
    metadata_path = root / 'metadata.json'
    metadata = (json.loads(metadata_path.read_text(encoding='utf-8'))
                if metadata_path.is_file() else metadata_template(version))
    check_metadata(metadata, version)
    for size, name in ((24, 'toolbar-24.png'), (48, 'toolbar-48.png'), (64, 'pcm-icon.png')):
        check_png(source / name, size)

    default_output = (root / 'heatmap_releases' / version
                      if (root / 'heatmap_tools').is_dir() else root / 'dist')
    out = Path(output or default_output)
    out.mkdir(parents=True, exist_ok=True)
    contents = {'plugins/' + name: (source / name).read_bytes() for name in FILES}
    contents['resources/icon.png'] = (source / 'pcm-icon.png').read_bytes()
    contents['metadata.json'] = (json.dumps(metadata, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(contents.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data, compresslevel=9)
    payload = buffer.getvalue()
    package = out / f'PCB_Heatmap-{version}-pcm.zip'
    if package.exists() and package.read_bytes() != payload:
        raise ValueError('Archive already exists with different content; use a clean output directory')
    package.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    submission = deepcopy(metadata)
    submission['versions'][0].update(
        download_url=f"{metadata['resources']['homepage'].rstrip('/')}/releases/download/v{version}/{package.name}",
        download_sha256=digest, download_size=len(payload),
        install_size=sum(map(len, contents.values())))
    directory = out / 'submission' / 'packages' / IDENTIFIER
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'metadata.json').write_text(
        json.dumps(submission, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    (directory / 'icon.png').write_bytes(contents['resources/icon.png'])
    (out / 'SHA256SUMS.txt').write_text(digest + '  ' + package.name + '\n', encoding='utf-8', newline='\n')
    report = dict(version=version, local_only=True, publishing_performed=False,
                  archive=str(package), sha256=digest, bytes=len(payload),
                  install_size=submission['versions'][0]['install_size'],
                  sources={name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in FILES})
    (out / 'package-checksums.json').write_text(
        json.dumps(report, indent=2) + '\n', encoding='utf-8', newline='\n')
    (out / 'metadata.json').write_bytes(contents['metadata.json'])
    return package


if __name__ == '__main__':
    print(build())
