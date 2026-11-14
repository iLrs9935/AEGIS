# nodes/__init__.py
import importlib
import os
import pkgutil
from core.security import NODE_CAPABILITIES

NODE_REGISTRY = {}


def register_node(name: str, category: str = "General", schema: dict = None):
    """
    节点注册装饰器
    """

    def decorator(func):
        NODE_REGISTRY[name] = {
            "func": func,
            "category": category,
            "schema": schema or {},
            "capabilities": NODE_CAPABILITIES.get(name),
        }
        return func

    return decorator


def _auto_scan_and_load():
    """
    [黑魔法] 动态扫描并加载当前目录下所有的 .py 节点文件
    """
    current_dir = os.path.dirname(__file__)

    # 遍历 nodes 目录下的所有模块
    for _, module_name, _ in pkgutil.iter_modules([current_dir]):
        try:
            # 动态导入模块，相当于自动执行 import nodes.xxx
            importlib.import_module(f".{module_name}", package=__name__)
        except ImportError as e:
            print(f"⚠️ 节点模块 [{module_name}] 加载失败，已跳过: {e}")


# 启动引擎时自动点火扫描
_auto_scan_and_load()
