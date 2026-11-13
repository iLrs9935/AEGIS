"""Offline release audit. Reports locations/rules, never credential values."""

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.release_files import is_public_file, public_files


RULES = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github-token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b"),
    "api-token": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    "aws-key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "jwt-token": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    "bearer-token": re.compile(r"(?i)\bBearer\s+[A-Za-z0-9_.-]{20,}"),
    "private-home": re.compile(r"(?i)[A-Z]:[/\\]+Users[/\\]+(?!Public\b|Default\b)[^\s/\\\"']+"),
    "private-network": re.compile(r"https?://(?:192\.168\.|10\.\d+\.\d+\.|172\.(?:1[6-9]|2\d|3[01])\.)"),
    "literal-credential": re.compile(
        r'''(?ix)["']?(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|client[_-]?secret)["']?\s*[:=]\s*["']([^"'\r\n]{8,})["']'''
    ),
}
URL = re.compile(r"https?://[^\s<>\"'`\)]+")


def placeholder(value):
    return (
        not value or value.startswith("${ENV:") or value.upper() in {
            "YOUR_KEY", "YOUR_API_KEY", "YOUR_TOKEN", "CHANGEME", "TEST-KEY", "EXAMPLE"
        } or value.startswith(("test-", "example-", "YOUR_"))
    )


def scan_text(text: str) -> list[tuple[int, str]]:
    findings = []
    for rule, pattern in RULES.items():
        for match in pattern.finditer(text):
            if rule == "literal-credential" and placeholder(match.group(1)):
                continue
            findings.append((text.count("\n", 0, match.start()) + 1, rule))
    for match in URL.finditer(text):
        try:
            parsed = urlsplit(match.group())
            host = (parsed.hostname or "").lower()
            line = text.count("\n", 0, match.start()) + 1
            if parsed.username is not None or parsed.password is not None:
                findings.append((line, "url-credentials"))
            if host == "api.day.app":
                key = parsed.path.strip("/")
                # Only explicit dummy endpoints used by tests/documentation.
                if key not in {"", "YOUR_KEY", "test-key", "secret/token"}:
                    findings.append((line, "bark-device-key"))
            for key, value in parse_qsl(parsed.query):
                if re.search(r"(?i)key|token|secret|password|signature", key) and not placeholder(value):
                    findings.append((line, "url-secret-query"))
        except ValueError:
            findings.append((text.count("\n", 0, match.start()) + 1, "malformed-url"))
    return sorted(set(findings))


def private_values(root: Path) -> set[str]:
    """Compare against this machine's secrets without displaying any of them."""
    path = root / "config.local.json"
    if not path.is_file():
        return set()
    settings = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(settings, dict):
        raise ValueError("config.local.json must be a mapping")
    values = set()
    for name, value in settings.items():
        if isinstance(value, str) and re.search(r"(?i)bark|key|token|secret|password", name) and len(value) >= 8:
            values.add(value)
            if "bark" in name.lower():
                key = urlsplit(value).path.strip("/").split("/")[0]
                if len(key) >= 8:
                    values.add(key)
    return values


def check_json_credentials(value):
    """Catch custom/self-hosted Bark URLs even when no local config exists."""
    if isinstance(value, list):
        return any(check_json_credentials(item) for item in value)
    if not isinstance(value, dict):
        return False
    for key, item in value.items():
        if isinstance(item, str) and re.search(
            r"(?i)bark.*(?:url|地址)|webhook|api[_-]?key|access[_-]?token|password|secret", key
        ):
            dummy_url = item.rstrip("/") in {"https://api.day.app/test-key", "https://api.day.app/YOUR_KEY"}
            if not placeholder(item) and not dummy_url:
                return True
        if check_json_credentials(item):
            return True
    return False


def check_release(root: Path) -> int:
    root = root.resolve()
    errors = []
    try:
        files = public_files(root)
        known = private_values(root)
    except (ValueError, OSError):
        print("FAIL: invalid release path or private configuration (contents hidden)")
        return 1
    for path in files:
        relative = path.relative_to(root).as_posix()
        raw = path.read_bytes()
        if any(value.encode("utf-8") in raw for value in known):
            errors.append(f"{relative}: known-local-secret")
        if path.suffix in {".png", ".ico"}:
            continue
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            errors.append(f"{relative}: non-UTF8-text")
            continue
        errors.extend(f"{relative}:{line}: {rule}" for line, rule in scan_text(text))
        try:
            if path.suffix == ".py":
                ast.parse(text, filename=relative)
            elif path.suffix == ".json":
                data = json.loads(text)
                if check_json_credentials(data):
                    errors.append(f"{relative}: literal-private-json-configuration")
                if "nodes" in data:
                    ids = [node["id"] for node in data["nodes"]]
                    if len(set(ids)) != len(ids):
                        raise ValueError
                    for edge in data["edges"]:
                        if edge["src_id"] not in ids or edge["tgt_id"] not in ids or edge["tgt_port"] != "IN":
                            raise ValueError
        except (SyntaxError, ValueError, KeyError, TypeError):
            errors.append(f"{relative}: invalid-source-or-workflow")

    # Inspect all index entries, including accidentally tracked ignored files.
    if (root / ".git").exists():
        result = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True)
        for name in result.stdout.decode("utf-8").split("\0"):
            if not name:
                continue
            if not is_public_file(Path(name)):
                errors.append(f"{name}: non-public-file-in-git-index")
                continue
            blob = subprocess.run(
                ["git", "-C", str(root), "show", f":{name}"],
                capture_output=True, check=True,
            ).stdout
            if any(value.encode("utf-8") in blob for value in known):
                errors.append(f"{name}: known-local-secret-in-git-index")
            if Path(name).suffix not in {".png", ".ico"}:
                try:
                    indexed_text = blob.decode("utf-8-sig")
                    errors.extend(f"{name}:{line}: git-index-{rule}" for line, rule in scan_text(indexed_text))
                    if Path(name).suffix == ".json" and check_json_credentials(json.loads(indexed_text)):
                        errors.append(f"{name}: literal-private-json-in-git-index")
                except (ValueError, UnicodeDecodeError):
                    errors.append(f"{name}: invalid-git-index-text")
    if errors:
        print("\n".join("FAIL: " + error for error in errors))
        return 1
    print(f"PASS: {len(files)} public files; no configured local secrets or supported credential patterns found")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    raise SystemExit(check_release(parser.parse_args().root))
