import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools.mark_all_cdkeys_used import mark_all_cdkeys_used


class MarkAllCdkeysUsedTests(unittest.TestCase):
    def test_marks_discovered_processed_and_legacy_codes_used(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            db_path = temp_path / "aegis_memory.db"
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE memory (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                ledger = {
                    "version": 2,
                    "discovered": {"CODE_A": {}, "CODE_B": {}},
                    "processed": {"CODE_A": {"result": "旧结果"}},
                    "seen_posts": ["post"],
                }
                connection.execute(
                    "INSERT INTO memory (key, value) VALUES (?, ?)",
                    ("mingchao_cdkeys", json.dumps(ledger)),
                )
                connection.execute(
                    "INSERT INTO memory (key, value) VALUES (?, ?)",
                    ("aegis_seen_cdkeys", json.dumps(["LEGACY_C"])),
                )
                connection.commit()
            finally:
                connection.close()

            result = mark_all_cdkeys_used(
                db_path=db_path,
                backup_dir=temp_path / "backups",
            )

            self.assertEqual(result["total"], 3)
            self.assertTrue(result["backup_path"].is_file())
            connection = sqlite3.connect(db_path)
            try:
                row = connection.execute(
                    "SELECT value FROM memory WHERE key = ?",
                    ("mingchao_cdkeys",),
                ).fetchone()
            finally:
                connection.close()
            updated = json.loads(row[0])
            self.assertEqual(
                set(updated["processed"]), {"CODE_A", "CODE_B", "LEGACY_C"}
            )
            self.assertTrue(
                all(
                    metadata["result"] == "已使用"
                    for metadata in updated["processed"].values()
                )
            )
            self.assertEqual(updated["seen_posts"], ["post"])


if __name__ == "__main__":
    unittest.main()
