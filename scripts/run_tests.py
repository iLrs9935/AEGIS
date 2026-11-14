"""Run every source test and write attributable JSON evidence.

Layers are exclusive; mock/native-Qt/Windows-API tags overlap. A real Qt test
with a mocked HAL is never evidence of real input, power or service delivery.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import platform
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from flatten(test)
        else:
            yield test


def classify(test):
    name = test.id()
    cls = type(test).__name__
    module = type(test).__module__
    native = ("test_real_child_receives_clean_dll_search_env_cwd_and_arguments",
              "test_real_windows_dll_search_is_reset_and_restored_even_on_error")
    if any(name.endswith(item) for item in native):
        layer = "windows_runtime"
    elif module == "test_execution_security" or cls in {"SystemPowerActionTests", "PowerHALTests", "DailyWorkflowPolicyTests", "OKWWNodePolicyTests"}:
        layer = "security"
    elif module in {"test_daily_runtime", "test_context_concurrency", "test_ui_interactions", "test_localization", "test_sdkdns_workflow", "test_llm_quickstart"} or cls in {"PublicWorkflowTests", "ReleaseAuditTests", "BackgroundWorkflowTests"}:
        layer = "integration"
    else:
        layer = "unit"
    # Conservative tagging: any test in a class using patches/test doubles is
    # tagged mock-assisted, including common setUp/helper seams. This definition
    # intentionally does not pretend to measure runtime Mock invocation counts.
    try:
        source = inspect.getsource(type(test))
    except (TypeError, OSError):
        source = ""
    uses_mocks = any(token in source for token in ("patch(", "patch.object", "patch.dict", "Mock(", "FakeVault", "self.run_daily("))
    tags = []
    if uses_mocks:
        tags.append("mock_assisted")
    if any(base.__name__ == "QtTestCase" for base in type(test).__mro__):
        tags.append("native_qt")
    if layer == "windows_runtime":
        tags.append("windows_api")
    return {"layer": layer, "tags": tags}


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = {}

    def startTest(self, test):
        super().startTest(test)
        self.records[test.id()] = {"id": test.id(), **classify(test), "outcome": "running", "subtests": {"passed": 0, "failed": 0, "skipped": 0}}

    def addSuccess(self, test):
        super().addSuccess(test)
        self.records[test.id()]["outcome"] = "passed"

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.records[test.id()]["outcome"] = "failed"

    def addError(self, test, err):
        super().addError(test, err)
        # setUpClass/tearDownClass errors may use a synthetic _ErrorHolder.
        if test.id() not in self.records:
            self.records[test.id()] = {"id": test.id(), "layer": "infrastructure", "tags": [], "outcome": "error"}
        else:
            self.records[test.id()]["outcome"] = "error"

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        if test.id() in self.records:
            self.records[test.id()]["outcome"] = "skipped"
        elif hasattr(test, "test_case"):
            self.records[test.test_case.id()]["subtests"]["skipped"] += 1

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        self.records[test.id()]["subtests"]["passed" if err is None else "failed"] += 1
        if err is not None:
            self.records[test.id()]["outcome"] = "failed"

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self.records[test.id()]["outcome"] = "expected_failure"

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.records[test.id()]["outcome"] = "unexpected_success"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    os.chdir(ROOT)
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    discovered = [test.id() for test in flatten(suite)]
    result = unittest.TextTestRunner(verbosity=2, resultclass=EvidenceResult).run(suite)
    records = list(result.records.values())
    outcomes = Counter(record["outcome"] for record in records)
    layers = {}
    for record in records:
        counter = layers.setdefault(record["layer"], Counter())
        counter[record["outcome"]] += 1
    from scripts.release_files import public_files
    hashes = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in public_files(ROOT) if path.suffix == ".py"}
    data = {
        "schema_version": 1, "utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(), "platform": platform.platform(),
        "discovered": len(discovered), "started": result.testsRun,
        "executed": sum(outcomes[key] for key in ("passed", "failed", "error", "expected_failure", "unexpected_success")),
        "passed": outcomes["passed"], "failed": outcomes["failed"], "errors": outcomes["error"],
        "skipped": outcomes["skipped"], "not_run": sorted(set(discovered) - result.records.keys()),
        "mock_assisted": sum("mock_assisted" in record["tags"] for record in records),
        "windows_api": sum("windows_api" in record["tags"] and record["outcome"] == "passed" for record in records),
        "native_qt": sum("native_qt" in record["tags"] and record["outcome"] == "passed" for record in records),
        "packaged_exe_scenarios": [], "layers": layers, "tests": records,
        "classification": "Exclusive layers; overlapping conservative class-level mock_assisted and native_qt/windows_api tags. Subtests are scenarios, not extra test methods.",
        "source_python_sha256": hashes,
        "unverified_external_features": ["real mouse/keyboard input", "Bark delivery", "Selenium remote site", "OK-WW/game", "hibernation", "optional llama model"],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Evidence: {args.report}; discovered={len(discovered)}, passed={data['passed']}, failed={data['failed']}, errors={data['errors']}, skipped={data['skipped']}")
    return 0 if result.wasSuccessful() and not data["not_run"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
