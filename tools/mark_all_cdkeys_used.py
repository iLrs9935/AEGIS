"""Mark every code in the packaged AEGIS ledger as used.

Close AEGIS before running this utility. A timestamped database backup is
created before the ledger is changed.
"""

import argparse
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = (
    PROJECT_ROOT
    / "dist"
    / "AEGIS Command Terminal"
    / "data"
    / "aegis_memory.db"
)
DEFAULT_BACKUP_DIR = PROJECT_ROOT / "backups"
DEFAULT_LEDGER_KEY = "mingchao_cdkeys"


def _load_json_value(connection: sqlite3.Connection, key: str, default):
    row = connection.execute(
        "SELECT value FROM memory WHERE key = ?", (key,)
    ).fetchone()
    if not row:
        return default
    try:
        return json.loads(row[0])
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"账本字段 {key!r} 不是有效 JSON") from error


def mark_all_cdkeys_used(
    db_path=DEFAULT_DB,
    backup_dir=DEFAULT_BACKUP_DIR,
    ledger_key=DEFAULT_LEDGER_KEY,
):
    db_path = Path(db_path).resolve()
    backup_dir = Path(backup_dir).resolve()
    if not db_path.is_file():
        raise FileNotFoundError(f"找不到 AEGIS 账本: {db_path}")

    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = backup_dir / f"aegis_memory.before_mark_all_used.{stamp}.db"

    # AEGIS 关闭后数据库没有旁路 WAL，直接复制能保留完整可恢复版本。
    try:
        shutil.copy2(db_path, backup_path)
    except PermissionError as error:
        raise RuntimeError("数据库仍被占用，请先完全关闭 AEGIS") from error

    now = datetime.now(timezone.utc).isoformat()
    connection = None
    try:
        connection = sqlite3.connect(db_path, timeout=2)
        try:
            connection.execute("BEGIN IMMEDIATE")
            ledger = _load_json_value(connection, ledger_key, {})
            if not isinstance(ledger, dict):
                raise ValueError(f"账本 {ledger_key!r} 的结构无效")

            discovered = ledger.get("discovered") or {}
            processed = ledger.get("processed") or {}
            if not isinstance(discovered, dict) or not isinstance(processed, dict):
                raise ValueError("兑换码账本的 discovered/processed 结构无效")

            codes = {
                str(code).strip().upper()
                for code in (*discovered.keys(), *processed.keys())
                if str(code).strip()
            }

            legacy_codes = _load_json_value(
                connection, "aegis_seen_cdkeys", []
            )
            if isinstance(legacy_codes, str):
                legacy_codes = [legacy_codes]
            if isinstance(legacy_codes, list):
                codes.update(
                    str(code).strip().upper()
                    for code in legacy_codes
                    if str(code).strip()
                )

            for code in sorted(codes):
                discovered.setdefault(
                    code,
                    {"source": "bulk_mark_used", "discovered_at": now},
                )
                processed[code] = {
                    "result": "已使用",
                    "processed_at": now,
                }

            ledger["discovered"] = discovered
            ledger["processed"] = processed
            ledger.setdefault("seen_posts", [])
            ledger.setdefault("version", 2)

            connection.execute(
                """
                INSERT INTO memory (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (ledger_key, json.dumps(ledger, ensure_ascii=False)),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    except sqlite3.OperationalError as error:
        if "locked" in str(error).lower():
            raise RuntimeError("数据库仍被占用，请先完全关闭 AEGIS") from error
        raise
    finally:
        if connection is not None:
            connection.close()

    return {
        "total": len(codes),
        "backup_path": backup_path,
        "db_path": db_path,
    }


def main():
    parser = argparse.ArgumentParser(
        description="把 AEGIS 账本中的全部鸣潮兑换码标记为已使用"
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--ledger-key", default=DEFAULT_LEDGER_KEY)
    args = parser.parse_args()

    result = mark_all_cdkeys_used(args.db, args.backup_dir, args.ledger_key)
    print(f"完成：{result['total']} 个兑换码已统一标记为『已使用』")
    print(f"账本备份：{result['backup_path']}")


if __name__ == "__main__":
    main()
