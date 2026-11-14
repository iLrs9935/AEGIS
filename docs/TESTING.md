# Test evidence conventions

Run all checks in a Windows environment with `requirements.txt` installed:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:PYTHONUTF8='1'
python -B scripts/run_tests.py --report release/test-report.json
```

`python -m unittest discover -s tests -v` remains supported. The evidence runner
uses the same discovery and executes every test; it does not select an easier
subset. A failure, error, unexpected success, or undispatched test returns a
nonzero exit code. Reports include Python/platform, test IDs, outcomes, source
Python SHA256 values, and subtest scenario counts. A failed subtest fails its
test method. Skipped or unexecuted checks are never counted as passes.

| Exclusive layer | Evidence |
| --- | --- |
| unit | Node functions, data contracts, utilities and test-report accounting |
| integration | Real Qt loading/threads, engine routing/loops, context concurrency, JSON and resource cleanup |
| security | Permissions, hostile/invalid imports, power guards and bypass attempts |
| windows_runtime | Two explicit Windows probes: real disposable child-process environment/arguments, real DLL-search reset/restore |
| packaged application | Separate actual EXE process; never included in source-test totals |

Tags overlap layers and each other. `mock_assisted` is deliberately conservative:
all methods of a test class using patches, shared fake objects, or mocked helper
seams receive this tag. It is **not** a runtime count of Mock calls or a count of
fully simulated tests. `native_qt` identifies real QApplication/QThreadPool test
classes. `windows_api` identifies the two explicit native probes. These tags
cannot be added to obtain a test total. A Windows host alone does not make a
mocked mouse/process/power test a real Windows operation.

The existing Windows probes use temporary processes/files and restore DLL state.
The child-process probe wraps Popen to observe a real child; its mock-assisted
and windows-api tags therefore both apply. No test operates the user's mouse,
types into real applications, kills a user process, deletes user files, sends
Bark, starts a game, or hibernates the host. Node contract tests mock native
mouse movement/clicks, keyboard, process launch/termination, power, memory vault,
browser, model and notification seams, including imports inside functions.

`tests/test_node_contracts.py` has authored normal-output, missing-input,
missing-configuration and invalid-container scenarios for all 41 registry
types. Additional scenarios cover numeric/empty boundaries, wrong field types,
25 external-dependency failures and recovery. Pure nodes have no external
dependency failure to simulate. Specific click, keyboard, OK-WW, crawler,
notification, branch and feedback tests provide deeper coverage. These are
foundation contracts, not an exhaustive validation of every configurable field
or every possible Windows/service failure. Subtests do not inflate method counts.

Actual package verification uses a disposable copy and a fresh output report:

```powershell
python scripts/verify_packaged.py --executable "release/my-build/dist/AEGIS Command Terminal/AEGIS Command Terminal.exe" --report release/package-report.json
./scripts/verify_packaged_startup.ps1 -ExecutablePath "release/my-build/dist/AEGIS Command Terminal/AEGIS Command Terminal.exe" -WorkflowPath examples/workflows/01_hello_text.json -Language en
./scripts/verify_packaged_startup.ps1 -ExecutablePath "release/my-build/dist/AEGIS Command Terminal/AEGIS Command Terminal.exe" -WorkflowPath examples/workflows/01_hello_text.json -Language zh
```

The EXE probe executes text, object-routing and array-feedback examples using
bundled Python/Qt, checks outputs and unchanged workflows, then verifies that an
unapproved system node is denied. That node is configured to preserve the
terminal even if a broken guard admits it. Reports require `sys.frozen` and bind
the executable SHA256. Startup probes independently check native window titles,
bundled Qt modules and Windows ICU. They do not validate external services.

CI runs every source layer on Windows Python 3.12/3.13/3.14 and uploads JSON
evidence even on failure. The release workflow checks the exact requested source
SHA on those versions before building, then requires bilingual EXE startup and
all four packaged scenarios before the existing draft-asset upload step. Editing
workflow YAML locally does not mean that a GitHub Actions run has occurred.

## User manual validation / 用户人工实测

On 2026-11-14 the user confirmed that real mouse/keyboard input, Bark delivery,
OK-WW/game operation and actual hibernation had passed manual testing. See
[MANUAL_VALIDATION.md](MANUAL_VALIDATION.md). This is a user-reported manual
record covering four areas, separate from the source-test totals and original
mock-assisted/native/packaged reports. The test execution dates and exact tested
artifact identities were not supplied. Automated external-operation tests remain
mocked; the user report does not change their classification.
