from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from belegdock import cli
from belegdock.workflow import Store


class RecoveryStatusLookupCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_status_lookup_checks_only_the_requested_document(self):
        Store(self.root).stage("account", "message-1", "part", "first.pdf", b"first")
        digest = Store(self.root).stage("account", "message-2", "part", "target.pdf", b"target")
        checked = []
        original = Store._blob_integrity

        def record_integrity(store, candidate, size):
            checked.append(candidate)
            return original(store, candidate, size)

        with patch.object(Store, "_blob_integrity", new=record_integrity):
            self.assertEqual(cli.document_status(self.root, digest), ("staged", True))

        self.assertEqual(checked, [digest])


if __name__ == "__main__":
    unittest.main()
