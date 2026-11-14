"""Verify a freshly built onedir EXE in a disposable copy, never the old release."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def verify(executable, report):
    executable = executable.resolve(strict=True)
    if os.name != "nt" or executable.suffix.lower() != ".exe":
        raise ValueError("Packaged verification requires a Windows EXE")
    if report.exists():
        raise ValueError("Choose a fresh evidence report path")
    expected_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="aegis-package-probe-") as directory:
        root = Path(directory)
        bundle = root / "app"
        shutil.copytree(executable.parent, bundle)
        output = root / "probe.json"
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(("AEGIS_", "PYTHON", "QT_"))}
        environment["PATH"] = os.pathsep.join([os.path.join(environment.get("SystemRoot", r"C:\Windows"), "System32"), environment.get("SystemRoot", r"C:\Windows")])
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        subprocess.run([str(bundle / executable.name), "--verify-package", str(output)],
                       cwd=root, env=environment, timeout=60, check=True, startupinfo=startup)
        data = json.loads(output.read_text(encoding="utf-8"))
        if not data.get("packaged") or data.get("executable_sha256") != expected_hash:
            raise RuntimeError("Package evidence identity mismatch")
        if len(data.get("scenarios", [])) != 4 or any(item.get("outcome") != "passed" for item in data["scenarios"]):
            raise RuntimeError("Incomplete package scenarios")
        report.parent.mkdir(parents=True, exist_ok=True)
        with report.open("x", encoding="utf-8") as target:
            json.dump(data, target, ensure_ascii=False, indent=2)
    print(f"PASS: actual EXE; 4 scenarios; SHA256 {expected_hash}; report={report}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    verify(args.executable, args.report)
