"""Resolve private settings at runtime without writing them into workflows."""

import json
import os
import re
import sys
from pathlib import Path


REFERENCE = re.compile(r"\$\{ENV:([A-Za-z_][A-Za-z0-9_]*)\}")


def application_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def private_setting(name: str) -> str:
    """Environment overrides the ignored config.local.json next to the app."""
    if name in os.environ:
        return os.environ[name]
    path = application_directory() / "config.local.json"
    if not path.is_file():
        return ""
    try:
        settings = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(settings, dict):
            raise ValueError
        value = settings.get(name, "")
        if not isinstance(value, str):
            raise ValueError
        return value
    except (OSError, ValueError):
        # Never include file contents or a decoder's exception in a log.
        raise ValueError("config.local.json 必须是有效的 JSON 字符串映射") from None


def resolve_config(value):
    """Resolve explicit ${ENV:NAME} references on a new copy, just before use."""
    if isinstance(value, dict):
        return {key: resolve_config(item) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_config(item) for item in value]
    if not isinstance(value, str):
        return value

    def replace(match):
        name = match.group(1)
        result = private_setting(name)
        if not result.strip():
            raise ValueError(f"未配置 {name}，请设置环境变量或 config.local.json")
        return result

    return REFERENCE.sub(replace, value)
