"""Single allowlist shared by the source exporter and release audit."""

from pathlib import Path


ROOT_FILES = {
    ".gitignore", ".gitattributes", "main.py", "pyinstaller.py",
    "AEGIS Command Terminal.spec", "readme.md", "AI_WORKFLOW_PROMPT.md",
    "requirements.txt", "requirements-build.txt", "config.local.example.json",
    "SECURITY.md", "RELEASE_REVIEW.md", "README.zh-CN.md", "LICENSE",
}
SOURCE_DIRS = {"core", "functions", "nodes", "ui", "tests", "scripts", "tools"}
IMAGE_FILES = {
    "docs/screenshots/main-en.png", "docs/screenshots/main-zh.png",
    "images/icons/LOGO.ico",
    *{f"images/cdkey_process/{name}.png" for name in
      ("1", "2", "3", "4", "5", "6", "6.1", "7", "7.1", "error", "error2")},
    "images/sdkdns/0.png", "images/sdkdns/1.png",
    *{f"images/鸣潮自运行/{name}.png" for name in ("done", "modechoose", "start")},
}


def is_public_file(relative: Path) -> bool:
    name = relative.as_posix()
    if relative.is_absolute() or ".." in relative.parts:
        return False
    if name in ROOT_FILES or name in IMAGE_FILES:
        return True
    if ".local." in name.lower():
        return False
    if "__pycache__" in relative.parts or any(part.startswith(".") for part in relative.parts[1:]):
        return False
    if relative.parts[0] in SOURCE_DIRS:
        return relative.suffix == ".py" or (
            relative.parts[0] == "scripts" and relative.suffix == ".ps1"
        ) or (
            relative.parts[:2] == ("tests", "fixtures") and relative.suffix == ".json"
        ) or name == "tools/全部CDKEY标记为已使用.cmd"
    return (
        relative.parts[:2] == ("examples", "workflows") and relative.suffix == ".json"
    ) or (
        relative.parts[0] in {"docs", "examples"} and relative.suffix == ".md"
    ) or (
        relative.parts[:2] == (".github", "workflows") and relative.suffix in {".yml", ".yaml"}
    )


def public_files(root: Path) -> list[Path]:
    root = root.resolve()
    candidates = [root / name for name in ROOT_FILES | IMAGE_FILES]
    for directory in SOURCE_DIRS | {"docs", "examples", ".github"}:
        base = root / directory
        if base.is_symlink():
            raise ValueError(f"Release directory cannot be a symbolic link: {directory}")
        if base.exists():
            candidates.extend(base.rglob("*"))
    files = set()
    for path in candidates:
        relative = path.relative_to(root)
        if not is_public_file(relative):
            continue
        if any(parent.is_symlink() for parent in (path, *path.parents) if parent != root.parent):
            raise ValueError(f"Release path cannot be a symbolic link: {relative}")
        if path.is_file():
            files.add(path)
    return sorted(files)
