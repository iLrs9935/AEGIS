"""Network notification helpers with verified delivery and a durable outbox."""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Callable


def _normalise_bark_url(bark_url: str) -> str:
    return (bark_url or "").strip().rstrip("/")


def _send_bark_once(
    bark_url: str,
    title: str,
    content: str,
    group: str = "AEGIS",
    level: str = "active",
    timeout: float = 10.0,
    opener: Callable | None = None,
) -> bool:
    url = _normalise_bark_url(bark_url)
    if not url:
        return False

    payload = {
        "title": str(title),
        "body": str(content),
        "group": str(group or "AEGIS"),
        "level": str(level or "active"),
        "isArchive": "1",
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "AEGIS-Command-Terminal/1.0",
        },
        method="POST",
    )
    open_request = opener or urllib.request.urlopen
    context = ssl.create_default_context()
    try:
        kwargs = {"timeout": max(1.0, float(timeout))}
        if opener is None:
            kwargs["context"] = context
        with open_request(request, **kwargs) as response:
            if int(getattr(response, "status", 0)) != 200:
                return False
            raw = response.read()
    except (OSError, ValueError, urllib.error.URLError):
        return False

    if not raw:
        return False
    try:
        result = json.loads(raw.decode("utf-8", errors="replace"))
    except (TypeError, ValueError):
        return False
    code = result.get("code") if isinstance(result, dict) else None
    return code in {200, "200"}


def _write_outbox_entry(outbox_directory: str, message: dict) -> bool:
    if not outbox_directory:
        return False
    directory = Path(outbox_directory)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        name = f"{time.time_ns()}-{uuid.uuid4().hex}.json"
        target = directory / name
        temporary = directory / f".{name}.tmp"
        temporary.write_text(
            json.dumps(message, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, target)
        return True
    except OSError:
        return False


def flush_bark_outbox(
    outbox_directory: str,
    timeout: float = 10.0,
    max_messages: int = 20,
    opener: Callable | None = None,
) -> dict:
    """Retry queued messages oldest-first, retaining every unconfirmed item."""

    directory = Path(outbox_directory)
    if not outbox_directory or not directory.is_dir():
        return {"delivered": 0, "remaining": 0}

    delivered = 0
    candidates = sorted(directory.glob("*.json"))[: max(0, int(max_messages))]
    for path in candidates:
        try:
            message = json.loads(path.read_text(encoding="utf-8"))
            success = _send_bark_once(
                message["bark_url"],
                message["title"],
                message["content"],
                message.get("group", "AEGIS"),
                message.get("level", "active"),
                timeout,
                opener,
            )
        except (KeyError, OSError, TypeError, ValueError):
            success = False
        if success:
            try:
                path.unlink()
                delivered += 1
            except OSError:
                pass

    return {
        "delivered": delivered,
        "remaining": len(list(directory.glob("*.json"))),
    }


def execute_reliable_bark_push(
    bark_url: str,
    title: str,
    content: str,
    *,
    group: str = "AEGIS",
    level: str = "active",
    attempts: int = 3,
    retry_delay: float = 2.0,
    timeout: float = 10.0,
    outbox_directory: str = "",
    opener: Callable | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict:
    """Confirm Bark HTTP/API success or atomically retain the notification."""

    url = _normalise_bark_url(bark_url)
    if not url:
        return {"delivered": False, "queued": False, "attempts": 0}

    if outbox_directory:
        flush_bark_outbox(outbox_directory, timeout=timeout, opener=opener)

    attempt_count = max(1, int(attempts))
    for index in range(attempt_count):
        if _send_bark_once(
            url, title, content, group, level, timeout=timeout, opener=opener
        ):
            return {
                "delivered": True,
                "queued": False,
                "attempts": index + 1,
            }
        if index + 1 < attempt_count:
            sleeper(max(0.0, float(retry_delay)))

    queued = _write_outbox_entry(
        outbox_directory,
        {
            "bark_url": url,
            "title": str(title),
            "content": str(content),
            "group": str(group or "AEGIS"),
            "level": str(level or "active"),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        },
    )
    return {
        "delivered": False,
        "queued": queued,
        "attempts": attempt_count,
    }


def execute_bark_push(bark_url: str, title: str, content: str) -> bool:
    """Backward-compatible verified Bark delivery for existing workflows."""

    return bool(
        execute_reliable_bark_push(
            bark_url,
            title,
            content,
            attempts=1,
            retry_delay=0.0,
            timeout=10.0,
        )["delivered"]
    )
