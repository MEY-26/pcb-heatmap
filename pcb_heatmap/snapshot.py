"""Private, immutable saved-PCB copies for the viewer and each calculation.

Only copies are created. The source design is never locked, saved or edited.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def create_snapshot(source, directory, *, expected_sha256=None, original_path=None):
    """Copy one stable read into a new run directory, with content provenance.

    KiCad can replace its saved file while we read. A changed identity, size,
    or timestamp causes a retry; a persistent change fails before analysis.
    An expected hash binds a solve copy to the exact board already displayed.
    """
    source = Path(source).resolve(strict=True)
    directory = Path(directory).resolve(strict=True)
    target = directory / 'board-snapshot.kicad_pcb'
    if source.suffix.lower() != '.kicad_pcb':
        raise ValueError('Select a saved .kicad_pcb file.')
    # Exclusive creation protects both earlier runs and any accidental design
    # path/symlink supplied as a destination.
    if target.exists() or target.is_symlink() or source == target:
        raise ValueError('A board snapshot already exists in this run folder.')
    pending = directory / 'board-snapshot.pending'
    if pending.exists() or pending.is_symlink():
        raise ValueError('A pending snapshot already exists in this run folder.')
    for attempt in range(3):
        before = source.stat()
        with source.open('rb') as stream:
            opened = os.fstat(stream.fileno())
            payload = stream.read()
            closed = os.fstat(stream.fileno())
        after = source.stat()
        signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
        if all(signature(s) == signature(before) for s in (opened, closed, after)) and len(payload) == before.st_size:
            break
    else:
        raise ValueError('The PCB was being saved while its snapshot was captured. Reload after saving.')
    sha = hashlib.sha256(payload).hexdigest()
    if expected_sha256 and sha != expected_sha256:
        raise ValueError('The displayed board snapshot changed. Reload the board.')
    with pending.open('xb') as stream:
        stream.write(payload)
    # Use exclusive target creation rather than replace: a snapshot must never
    # overwrite any pre-existing file, even if another process created it.
    try:
        with target.open('xb') as stream:
            stream.write(payload)
    finally:
        pending.unlink(missing_ok=True)
    return dict(path=str(target), sha256=sha,
                original_path=str(Path(original_path or source).resolve()),
                captured_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
