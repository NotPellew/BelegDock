import importlib.util
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location("replay_red", Path(__file__).resolve().parents[2] / "scripts/replay_red.py")
REPLAY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPLAY)


class RedReplayTests(unittest.TestCase):
    def report(self, content):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "result.xml"
        path.write_text('<testsuites><testsuite>' + content + '</testsuite></testsuites>')
        return path

    def test_returns_named_intended_failures(self):
        path = self.report('<testcase classname="TestFeature" name="test_value"><failure message="AssertionError: missing behavior">AssertionError: missing behavior</failure></testcase>')
        self.assertEqual(REPLAY.validate_report(path, {"TestFeature.test_value"}, 1, {"AssertionError"}), ["TestFeature.test_value"])

    def test_passing_skipped_missing_and_unrelated_errors_are_not_red(self):
        cases = [
            '<testcase classname="TestFeature" name="test_value"/>',
            '<testcase classname="TestFeature" name="test_value"><skipped/></testcase>',
            '',
            '<testcase classname="TestFeature" name="test_value"><error>ImportError</error></testcase>',
            '<testcase classname="TestFeature" name="test_value"><failure message="ModuleNotFoundError">ModuleNotFoundError: absent</failure></testcase>',
        ]
        for content in cases:
            with self.subTest(content=content):
                with self.assertRaises(ValueError):
                    REPLAY.validate_report(self.report(content), {"TestFeature.test_value"}, 1, {"AssertionError"})

    def test_zero_exit_status_is_not_red(self):
        path = self.report('<testcase classname="TestFeature" name="test_value"><failure message="AssertionError">AssertionError</failure></testcase>')
        with self.assertRaises(ValueError):
            REPLAY.validate_report(path, {"TestFeature.test_value"}, 0, {"AssertionError"})

    def test_duplicate_case_cannot_replace_missing_case(self):
        case = '<testcase classname="TestFeature" name="test_value"><failure message="AssertionError">AssertionError</failure></testcase>'
        with self.assertRaises(ValueError):
            REPLAY.validate_report(self.report(case + case), {"TestFeature.test_value", "TestFeature.test_other"}, 1, {"AssertionError"})

    def test_explicit_missing_behavior_stub_is_allowed_only_when_declared(self):
        path = self.report('<testcase classname="TestFeature" name="test_value"><failure message="NotImplementedError: behavior">NotImplementedError: behavior</failure></testcase>')
        with self.assertRaises(ValueError):
            REPLAY.validate_report(path, {"TestFeature.test_value"}, 1, {"AssertionError"})
        self.assertEqual(REPLAY.validate_report(path, {"TestFeature.test_value"}, 1, {"NotImplementedError"}), ["TestFeature.test_value"])
