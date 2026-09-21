import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

from belegdock import cli


class GermanCliParseErrorTests(unittest.TestCase):
    def invoke(self, arguments):
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error), patch.object(cli, "dispatch") as dispatch:
            status = cli.main(arguments)
        return status, output.getvalue(), error.getvalue(), dispatch

    def test_missing_required_arguments_is_german_without_dispatch(self):
        status, output, error, dispatch = self.invoke(["stage"])

        self.assertEqual(status, 2)
        self.assertEqual(output, "")
        self.assertIn("Folgende Argumente sind erforderlich", error)
        self.assertNotIn("the following arguments are required", error)
        dispatch.assert_not_called()

    def test_missing_option_value_is_german_without_dispatch(self):
        status, output, error, dispatch = self.invoke(["--data-dir"])

        self.assertEqual(status, 2)
        self.assertEqual(output, "")
        self.assertIn("Ein Argument wird erwartet", error)
        self.assertNotIn("expected one argument", error)
        dispatch.assert_not_called()

    def test_invalid_subcommand_is_german_without_dispatch(self):
        status, output, error, dispatch = self.invoke(["invalid-command"])

        self.assertEqual(status, 2)
        self.assertEqual(output, "")
        self.assertIn("Ungültige Auswahl", error)
        self.assertNotIn("invalid choice", error)
        self.assertNotIn("choose from", error)
        dispatch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
