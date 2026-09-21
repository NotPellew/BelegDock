import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

from belegdock import cli
from belegdock.workflow import DocumentRejected, LocalIntegrityError, TransferActiveError


DIGEST = "a" * 64


class GermanCliErrorSurfaceTests(unittest.TestCase):
    def invoke_generic(self, arguments, document_status=None):
        output, error = StringIO(), StringIO()
        patches = [patch.object(cli, "dispatch", side_effect=RuntimeError("private failure"))]
        if document_status is not None:
            patches.append(patch.object(cli, "document_status", return_value=document_status))
        with redirect_stdout(output), redirect_stderr(error):
            with patches[0], patches[1] if len(patches) > 1 else _NullContext():
                status = cli.main(["--data-dir", "/tmp/belegdock-test-data", *arguments])
        return status, output.getvalue(), error.getvalue()

    def test_generic_cli_failure_states_are_german(self):
        cases = (
            (["stage", "--label", "LABEL", "--select", "ID"], None, "Vorbereiten fehlgeschlagen"),
            (["upload", "not-a-hash"], None, "Ungültiger Dokument-Hash"),
            (["upload", DIGEST], ("local_integrity_failed", True), "Lokale Dokumentintegrität"),
            (["upload", DIGEST], ("rejected", True), "Dokument wurde abgelehnt"),
            (["upload", DIGEST], ("uploaded", True), "Upload für"),
            (["upload", DIGEST], ("uploading", True), "Senden für"),
            (["recover-upload", "not-a-hash"], None, "Ungültiger Dokument-Hash"),
            (["recover-upload", DIGEST], ("local_integrity_failed", True), "Lokale Dokumentintegrität"),
            (["recover-upload", DIGEST], ("uploading", True), "Wiederherstellung fehlgeschlagen"),
            (["recover-upload", DIGEST], ("staged", True), "Wiederherstellung wurde nicht gestartet"),
            (
                ["reconcile", "not-a-hash", "--file-id", "FILE_ID", "--voucher-id", "VOUCHER_ID"],
                None,
                "Ungültiger Dokument-Hash",
            ),
            (
                ["reconcile", DIGEST, "--file-id", "FILE_ID", "--voucher-id", "VOUCHER_ID"],
                ("local_integrity_failed", True),
                "Lokale Dokumentintegrität",
            ),
            (
                ["reconcile", DIGEST, "--file-id", "FILE_ID", "--voucher-id", "VOUCHER_ID"],
                ("uploading", True),
                "Abstimmung ist nicht möglich",
            ),
            (
                ["reconcile", DIGEST, "--file-id", "FILE_ID", "--voucher-id", "VOUCHER_ID"],
                ("staged", True),
                "Abstimmung wurde nicht gestartet",
            ),
        )

        for arguments, document_status, expected in cases:
            with self.subTest(arguments=arguments):
                status, output, error = self.invoke_generic(arguments, document_status)

                self.assertEqual(status, 1)
                self.assertEqual(output, "")
                self.assertIn(expected, error)
                self.assertNotIn("failed", error.lower())
                self.assertNotIn("retry", error.lower())

    def test_exception_handlers_are_german(self):
        cases = (
            (DocumentRejected(406), ["upload", DIGEST], "Lexware hat den Upload abgelehnt"),
            (LocalIntegrityError(), ["documents"], "Lokale Daten sind nicht verfügbar"),
            (TransferActiveError(), ["upload", DIGEST], "Ein anderer Vorgang ist aktiv"),
            (TransferActiveError(), ["recover-upload", DIGEST], "Wiederherstellung fehlgeschlagen"),
        )

        for exception, arguments, expected in cases:
            with self.subTest(arguments=arguments):
                output, error = StringIO(), StringIO()
                with redirect_stdout(output), redirect_stderr(error), patch.object(
                    cli, "dispatch", side_effect=exception
                ):
                    status = cli.main(arguments)

                self.assertEqual(status, 1)
                self.assertEqual(output.getvalue(), "")
                self.assertIn(expected, error.getvalue())
                self.assertNotIn("failed", error.getvalue().lower())


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


if __name__ == "__main__":
    unittest.main()
