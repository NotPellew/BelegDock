import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from belegdock.workflow import Store


class WindowsLockOffsetTests(unittest.TestCase):
    def test_windows_lock_and_unlock_use_the_first_byte_of_a_nonempty_file(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        lock_path = Path(temporary.name) / "lock"
        lock_path.write_bytes(b"locked")
        positions = []

        class FakeMsvcrt:
            LK_NBLCK = 1
            LK_UNLCK = 2

            @staticmethod
            def locking(descriptor, mode, length):
                positions.append((mode, length, os.lseek(descriptor, 0, os.SEEK_CUR)))

        with lock_path.open("r+b") as handle, patch("builtins.__import__", return_value=FakeMsvcrt):
            handle.seek(4)
            Store._windows_lock(handle, "LK_NBLCK")
            handle.seek(2)
            Store._windows_lock(handle, "LK_UNLCK")

        self.assertEqual(positions, [(1, 1, 0), (2, 1, 0)])


if __name__ == "__main__":
    unittest.main()
