"""Build using the reviewed spec without deleting sources or local settings."""
import os
from pathlib import Path


def main():
    from PyInstaller.__main__ import run
    from scripts.check_release import check_release

    root = Path(__file__).resolve().parent
    if check_release(root):
        raise SystemExit("Release checks failed; build cancelled.")
    os.chdir(root)
    run(["--noconfirm", str(root / "AEGIS Command Terminal.spec")])


if __name__ == "__main__":
    main()
