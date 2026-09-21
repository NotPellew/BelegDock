import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

from belegdock import cli


class GermanCliParseErrorEdgeTests(unittest.TestCase):
    def invoke(self, arguments):
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error), patch.object(cli, "dispatch") as dispatch:
            status = cli.main(arguments)
        return status, output.getvalue(), error.getvalue(), dispatch

    def test_explicit_help_argument_error_is_german_without_dispatch(self):
        status, output, error, dispatch = self.invoke(["--help=x"])

        self.assertEqual(status, 2)
        self.assertEqual(output, "")
        self.assertIn("Explizites Argument", error)
        self.assertNotIn("ignored explicit argument", error)
        dispatch.assert_not_called()

    def test_explicit_version_argument_error_is_german_without_dispatch(self):
        status, output, error, dispatch = self.invoke(["--version=x"])

        self.assertEqual(status, 2)
        self.assertEqual(output, "")
        self.assertIn("Explizites Argument", error)
        self.assertNotIn("ignored explicit argument", error)
        dispatch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
