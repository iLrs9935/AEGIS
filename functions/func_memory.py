# functions/func_memory.py
import json
import os
import sqlite3
import sys


class _MemoryVault:
    def __init__(self):
        # 智能定位存储路径，完美兼容源码与 EXE 运行
        if getattr(sys, "frozen", False):
            # EXE 运行模式：放在 EXE 所在的同级 data 目录下
            base_dir = os.path.dirname(sys.executable)
        else:
            # 源码运行模式：使用项目根目录
            # 注意：只退一级 ".."！千万别写两个！
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

        data_dir = os.path.join(base_dir, "data")

        # 终极防御：自动创建 data 目录
        os.makedirs(data_dir, exist_ok=True)

        self.db_path = os.path.join(data_dir, "aegis_memory.db")
        self._init_db()

    def _init_db(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS memory (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """)
        except Exception as e:
            print(f"⚠️ [HAL] 记忆保险库初始化失败: {e}")

    def write(self, key: str, value: any) -> bool:
        """[HAL] 降维写入，Python对象自动转JSON字符串"""
        try:
            str_value = json.dumps(value, ensure_ascii=False)
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO memory (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                    (key, str_value),
                )
            return True
        except Exception as e:
            print(f"⚠️ [HAL] 写入记忆失败 ({key}): {e}")
            return False

    def read(self, key: str) -> any:
        """[HAL] 升维读取，如果是JSON则自动还原为Python对象"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT value FROM memory WHERE key = ?", (key,))
                row = cursor.fetchone()
                if row:
                    try:
                        return json.loads(row[0])
                    except json.JSONDecodeError:
                        return row[0]
                return None
        except Exception as e:
            print(f"⚠️ [HAL] 读取记忆失败 ({key}): {e}")
            return None

    def delete(self, key: str) -> bool:
        """[HAL] 定点擦除"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM memory WHERE key = ?", (key,))
            return True
        except Exception as e:
            print(f"⚠️ [HAL] 删除记忆失败 ({key}): {e}")
            return False

    def wipe_all(self) -> bool:
        """[HAL] 全盘格式化"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM memory")
            return True
        except Exception as e:
            print(f"⚠️ [HAL] 全盘擦除失败: {e}")
            return False


# 暴露出一个统一的底层接口句柄
vault = _MemoryVault()
