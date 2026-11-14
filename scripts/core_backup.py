#!/usr/bin/env python3
"""Dozor's fixed Lineage core SSH entrypoint and pre-deploy backup gate.

Install beside receiver.py and profile.json in /srv/deploy/lineage-core.
SSH allows prepare-backup REVISION plus the unchanged receiver commands.
The receiver invokes this script with --check under its deployment lock.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

ROOT = Path('/srv/deploy/lineage-core')
BACKUPS = Path('/srv/recovery/backups/lineage-core')
DATABASE = 'arkhiv_core_preview'
CONTAINER = 'arkhiv-live-music-metadata-dev'
MAX_AGE = 3600


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def validate(receipt, revision, now):
    if receipt['revision'] != revision:
        raise ValueError('Backup belongs to a different revision; prepare it again')
    if not 0 <= now - receipt['started_at'] <= MAX_AGE:
        raise ValueError('Backup is older than one hour; prepare it again')
    path = BACKUPS / receipt['file']
    if path.parent != BACKUPS or path.suffix != '.dump':
        raise ValueError('Invalid backup path')
    if path.stat().st_size != receipt['bytes'] or digest(path) != receipt['sha256']:
        raise ValueError('Backup bytes changed; prepare it again')
    return path


def list_dump(path):
    with path.open('rb') as source:
        subprocess.run(['docker', 'exec', '-i', CONTAINER, 'pg_restore', '-l'],
                       stdin=source, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=True, timeout=60)


def main():
    os.umask(0o077)
    sys.path.insert(0, str(ROOT))
    import receiver
    profile = json.loads((ROOT / 'profile.json').read_text())
    marker = BACKUPS / 'prepared.json'
    if sys.argv[1:] == ['--check']:
        receipt = json.loads(marker.read_text())
        receiver.assert_current_main(profile, receipt['revision'])
        path = validate(receipt, receipt['revision'], time.time())
        list_dump(path)
        # A failed migration must get a new backup, too. Never reuse this gate.
        marker.rename(BACKUPS / 'consumed.json')
        print('Validated backup', path.name)
        return
    if sys.argv[1:]:
        raise ValueError('Unexpected local argument')
    command = shlex.split(os.environ.get('SSH_ORIGINAL_COMMAND', ''))
    if command and command[0] == 'prepare-backup':
        if len(command) != 2 or not re.fullmatch('[0-9a-f]{40}', command[1]):
            raise ValueError('prepare-backup requires a full revision')
        revision = command[1]
        BACKUPS.mkdir(mode=0o700, parents=True, exist_ok=True)
        state = Path(profile['state'])
        state.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (state / 'deploy.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            receiver.assert_current_main(profile, revision)
            marker.unlink(missing_ok=True)
            started = time.time()
            path = BACKUPS / (time.strftime('lineage-%Y%m%dT%H%M%SZ', time.gmtime()) + '.dump')
            part = path.with_suffix('.part')
            with part.open('xb') as output:
                # PostgreSQL also has a deadline if the SSH client disappears.
                subprocess.run(['docker', 'exec', '-e', 'PGOPTIONS=-c statement_timeout=3000000',
                                CONTAINER, 'pg_dump', '-U', 'arkhiv', '-d', DATABASE, '-Fc'],
                               stdout=output, stderr=subprocess.DEVNULL, check=True, timeout=3100)
                output.flush()
                os.fsync(output.fileno())
            list_dump(part)
            part.rename(path)
            receipt = {'revision': revision, 'started_at': started, 'file': path.name,
                       'bytes': path.stat().st_size, 'sha256': digest(path)}
            receiver.assert_current_main(profile, revision)
            validate(receipt, revision, time.time())
            temporary = marker.with_suffix('.tmp')
            temporary.write_text(json.dumps(receipt) + '\n')
            temporary.replace(marker)
            print('Backup prepared and checked:', path.name)
        return
    # receiver.py validates every other command and acquires the same lock.
    os.execv(sys.executable, [sys.executable, str(ROOT / 'receiver.py'),
                            '--profile', str(ROOT / 'profile.json')])


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Never emit resolved database credentials or subprocess diagnostics.
        print('Core backup refused (' + type(error).__name__ + '); inspect host backup state', file=sys.stderr)
        sys.exit(1)
