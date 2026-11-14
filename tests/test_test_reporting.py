"""Failure/skip/subtest accounting must remain honest when checks fail."""
import io
import unittest
from unittest.mock import patch

from core.package_probe import verify_package
from scripts.run_tests import EvidenceResult
from scripts.verify_packaged import verify


class TestEvidenceTests(unittest.TestCase):
    def run_probe(self, case):
        return unittest.TextTestRunner(stream=io.StringIO(), resultclass=EvidenceResult).run(unittest.defaultTestLoader.loadTestsFromTestCase(case))

    def test_failed_subtest_is_one_failed_method_not_a_pass(self):
        class Probe(unittest.TestCase):
            def test_scenarios(self):
                for value in (1, 2):
                    with self.subTest(value=value):
                        self.assertEqual(value, 1)
        result = self.run_probe(Probe)
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(result.testsRun, 1)
        record = next(iter(result.records.values()))
        self.assertEqual(record["outcome"], "failed")
        self.assertEqual(record["subtests"], {"passed": 1, "failed": 1, "skipped": 0})

    def test_skip_and_error_are_never_counted_as_success(self):
        class Probe(unittest.TestCase):
            @unittest.skip("not run")
            def test_skipped(self):
                raise AssertionError("must not run")
            def test_error(self):
                raise RuntimeError("fixture failed")
        result = self.run_probe(Probe)
        self.assertEqual(sorted(record["outcome"] for record in result.records.values()), ["error", "skipped"])

    def test_source_process_cannot_claim_packaged_validation(self):
        with patch("core.package_probe.sys.frozen", False, create=True):
            with self.assertRaisesRegex(RuntimeError, "actual frozen executable"):
                verify_package(None, "unused.json")

    def test_package_verifier_rejects_reused_report(self):
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / "test.exe"
            exe.write_bytes(b"not executed")
            report = root / "existing.json"
            report.write_text("preserve", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "fresh"):
                verify(exe, report)
            self.assertEqual(report.read_text(), "preserve")
