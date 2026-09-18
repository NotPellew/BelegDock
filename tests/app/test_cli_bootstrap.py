import unittest
from contextlib import redirect_stdout
from io import StringIO

from belegdock.cli import main


class CliBootstrapTests(unittest.TestCase):
    def run_cli(self, *arguments):
        output = StringIO()
        with redirect_stdout(output):
            status = main(list(arguments))
        return status, output.getvalue()

    def test_help_describes_the_early_stage_cli(self):
        status, output = self.run_cli("--help")

        self.assertEqual(status, 0)
        self.assertIn("BelegDock", output)
        self.assertIn("early-stage", output)

    def test_version_reports_the_package_version(self):
        status, output = self.run_cli("--version")

        self.assertEqual(status, 0)
        self.assertEqual(output.strip(), "0.1.0.dev0")


if __name__ == "__main__":
    unittest.main()
