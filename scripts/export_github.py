"""Create a source-only ZIP after auditing exactly the public allowlist."""

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.check_release import check_release
from scripts.release_files import public_files


def export_source(root: Path, output: Path):
    root, output = root.resolve(), output.resolve()
    if output.exists():
        raise ValueError("Output already exists; choose a new ZIP filename")
    if check_release(root):
        raise ValueError("Release audit failed; nothing exported")
    files = public_files(root)
    if output in files or output.suffix.lower() != ".zip":
        raise ValueError("Output must be a ZIP outside the public file list")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(root).as_posix())
        archive.writestr("SOURCE_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"Exported {len(files)} files to {output.name}")
    print("SHA256: " + hashlib.sha256(output.read_bytes()).hexdigest())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("release/AEGIS-github-source.zip"))
    args = parser.parse_args()
    export_source(Path(__file__).resolve().parents[1], args.output)
