import unittest
from contextlib import redirect_stdout
from io import StringIO

from belegdock.cli import main


class GermanCliPositionalHelpTests(unittest.TestCase):
    def test_subcommands_do_not_render_english_positional_heading(self):
        for command in ("upload", "recover-upload", "reconcile"):
            with self.subTest(command=command):
                output = StringIO()
                with redirect_stdout(output):
                    status = main([command, "--help"])

                self.assertEqual(status, 0)
                self.assertIn("Aufruf:", output.getvalue())
                self.assertIn("Optionen:", output.getvalue())
                self.assertNotIn("positional arguments:", output.getvalue())
                self.assertIn("Positionsargumente:", output.getvalue())


if __name__ == "__main__":
    unittest.main()
