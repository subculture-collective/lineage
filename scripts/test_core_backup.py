from pathlib import Path
import tempfile
import os
import unittest
from unittest.mock import patch

import core_backup


class BackupGate(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.patch = patch.object(core_backup, 'BACKUPS', self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.dump = self.root / 'backup.dump'
        self.dump.write_bytes(b'checked backup')
        self.dump.chmod(0o400)
        self.receipt = dict(revision='a' * 40, started_at=100, file=self.dump.name,
                            bytes=self.dump.stat().st_size, sha256=core_backup.digest(self.dump), fingerprint=core_backup.fingerprint(self.dump))

    def test_intact_recent_dump(self):
        self.assertEqual(core_backup.validate(self.receipt, 'a' * 40, 200), self.dump)

    def test_stale_or_future_dump(self):
        for now in (99, 3701):
            with self.subTest(now=now), self.assertRaises(ValueError):
                core_backup.validate(self.receipt, 'a' * 40, now)

    def test_wrong_revision(self):
        with self.assertRaises(ValueError):
            core_backup.validate(self.receipt, 'b' * 40, 200)

    def test_modified_dump(self):
        self.dump.chmod(0o600)
        self.dump.write_bytes(b'broken! backup')
        os.utime(self.dump, ns=(1, 1))
        self.dump.chmod(0o400)
        with self.assertRaises(ValueError):
            core_backup.validate(self.receipt, 'a' * 40, 200)

    def test_missing_dump(self):
        self.dump.unlink()
        with self.assertRaises(FileNotFoundError):
            core_backup.validate(self.receipt, 'a' * 40, 200)

    def test_path_escape(self):
        self.receipt['file'] = '../backup.dump'
        with self.assertRaises(ValueError):
            core_backup.validate(self.receipt, 'a' * 40, 200)


if __name__ == '__main__':
    unittest.main()
