import json
import os
import sys

from PyQt6.QtGui import QColor

# ================= 智能识别项目根目录 =================
if getattr(sys, "frozen", False):
    # 如果是打包后的 exe 运行，配置文件放在 exe 同级目录
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # 如果是源码运行，配置文件放在项目根目录 (ui文件夹的上一级)
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

CONFIG_FILE = os.path.join(BASE_DIR, "aegis_settings.json")
# ====================================================


class Theme:
    """AEGIS 全局动态主题引擎与记忆体"""

    EDGE_STYLES = {"curve", "orthogonal", "circuit"}

    PRESETS = {
        "Command Terminal": {
            "BG_COLOR": "#1E1E1E",
            "SCENE_BG": "#222222",
            "GRID_COLOR": "#2A2A2A",
            "NODE_BG": "#353535",
            "NODE_TITLE_BG": "#3F51B5",
            "NODE_BORDER_DEFAULT": "#111111",
            "NODE_BORDER_SELECTED": "#FFFFFF",
            "NODE_TEXT": "#FFFFFF",
            "NODE_TEXT_DIM": "#AAAAAA",
            "PORT_BG_DEFAULT": "#555555",
            "PORT_BG_CONNECTED": "#00E676",
            "PORT_BG_HOVER": "#00B0FF",
            "EDGE_DEFAULT": "#AAAAAA",
            "EDGE_ACTIVE": "#00E676",
            "EDGE_SELECTED": "#FFFFFF",
            "EDGE_SELECTED_GLOW": (0, 230, 118, 100),
            "INPUT_BG": "#222222",
            "INPUT_TEXT": "#EEEEEE",
            "INPUT_BORDER": "#111111",
            "TEXTAREA_BG": "#1A1A1A",
            "TEXTAREA_TEXT": "#A6E22E",
            "UI_HIGHLIGHT": "#3F51B5",
            "UI_HIGHLIGHT_TEXT": "#FFFFFF",
        },
        "夜之城": {
            "BG_COLOR": "#0D0E15",
            "SCENE_BG": "#131520",
            "GRID_COLOR": "#1F2233",
            "NODE_BG": "#1A1C29",
            "NODE_TITLE_BG": "#E92A67",
            "NODE_BORDER_DEFAULT": "#2D314A",
            "NODE_BORDER_SELECTED": "#00E5FF",
            "NODE_TEXT": "#E0E3F0",
            "NODE_TEXT_DIM": "#7A81A5",
            "PORT_BG_DEFAULT": "#3B426B",
            "PORT_BG_CONNECTED": "#00E5FF",
            "PORT_BG_HOVER": "#E92A67",
            "EDGE_DEFAULT": "#58608C",
            "EDGE_ACTIVE": "#E92A67",
            "EDGE_SELECTED": "#FFFFFF",
            "EDGE_SELECTED_GLOW": (0, 229, 255, 120),
            "INPUT_BG": "#12141D",
            "INPUT_TEXT": "#00E5FF",
            "INPUT_BORDER": "#2D314A",
            "TEXTAREA_BG": "#0A0B10",
            "TEXTAREA_TEXT": "#FFD600",
            "UI_HIGHLIGHT": "#E92A67",
            "UI_HIGHLIGHT_TEXT": "#FFFFFF",
        },
        "AEGIS Classic": {
            "BG_COLOR": "#F7F9FC",
            "SCENE_BG": "#EEF3F8",
            "GRID_COLOR": "#D3DEE9",
            "NODE_BG": "#FFFFFF",
            "NODE_TITLE_BG": "#E8F0FE",
            "NODE_TITLE_TEXT": "#17345C",
            "NODE_BORDER_DEFAULT": "#CBD6E2",
            "NODE_BORDER_SELECTED": "#2563EB",
            "NODE_TEXT": "#172033",
            "NODE_TEXT_DIM": "#64748B",
            "PORT_BG_DEFAULT": "#94A3B8",
            "PORT_BG_CONNECTED": "#2563EB",
            "PORT_BG_HOVER": "#0EA5E9",
            "EDGE_DEFAULT": "#8292A6",
            "EDGE_ACTIVE": "#2563EB",
            "EDGE_SELECTED": "#0F172A",
            "EDGE_SELECTED_GLOW": (37, 99, 235, 72),
            "INPUT_BG": "#F8FAFC",
            "INPUT_TEXT": "#172033",
            "INPUT_BORDER": "#C7D2DF",
            "TEXTAREA_BG": "#F3F7FB",
            "TEXTAREA_TEXT": "#334155",
            "UI_HIGHLIGHT": "#2563EB",
            "UI_HIGHLIGHT_TEXT": "#FFFFFF",
            "SURFACE_ALT": "#EDF2F7",
            "MENU_BG": "#FFFFFF",
            "MENU_TEXT": "#172033",
            "MENU_BORDER": "#CBD6E2",
            "MENU_SEPARATOR": "#E2E8F0",
            "TOOLTIP_BG": "#172033",
            "TOOLTIP_TEXT": "#F8FAFC",
            "CONSOLE_BG": "#FFFFFF",
            "CONSOLE_TEXT": "#334155",
            "DISABLED_TEXT": "#94A3B8",
            "RUN_BG": "#15803D",
            "STOP_BG": "#DC2626",
        },
        "波普撞色": {
            "BG_COLOR": "#F4F0EA",
            "SCENE_BG": "#FAFAFA",
            "GRID_COLOR": "#E5E5E5",
            "NODE_BG": "#FFFFFF",
            "NODE_TITLE_BG": "#7C3AED",
            "NODE_TITLE_TEXT": "#FFFFFF",
            "NODE_BORDER_DEFAULT": "#1E1E1E",
            "NODE_BORDER_SELECTED": "#EC4899",
            "NODE_TEXT": "#1A1A1A",
            "NODE_TEXT_DIM": "#6B7280",
            "PORT_BG_DEFAULT": "#1E1E1E",
            "PORT_BG_CONNECTED": "#10B981",
            "PORT_BG_HOVER": "#F59E0B",
            "EDGE_DEFAULT": "#1E1E1E",
            "EDGE_ACTIVE": "#EC4899",
            "EDGE_SELECTED": "#00E5FF",
            "EDGE_SELECTED_GLOW": (236, 72, 153, 60),
            "INPUT_BG": "#F3F4F6",
            "INPUT_TEXT": "#111827",
            "INPUT_BORDER": "#1E1E1E",
            "TEXTAREA_BG": "#F3F4F6",
            "TEXTAREA_TEXT": "#111827",
            "UI_HIGHLIGHT": "#7C3AED",
            "UI_HIGHLIGHT_TEXT": "#FFFFFF",
        },
        "Abyssal": {
            "BG_COLOR": "#030305",
            "SCENE_BG": "#08090C",
            "GRID_COLOR": "#111218",
            "NODE_BG": "#13151C",
            "NODE_TITLE_BG": "#2D004D",
            "NODE_TITLE_TEXT": "#E0C8FF",
            "NODE_BORDER_DEFAULT": "#1E2233",
            "NODE_BORDER_SELECTED": "#9D00FF",
            "NODE_TEXT": "#B0B5C0",
            "NODE_TEXT_DIM": "#4A5166",
            "PORT_BG_DEFAULT": "#2A2D3D",
            "PORT_BG_CONNECTED": "#FFB300",
            "PORT_BG_HOVER": "#FFE066",
            "EDGE_DEFAULT": "#2A2D3D",
            "EDGE_ACTIVE": "#FFB300",
            "EDGE_SELECTED": "#FFAA00",
            "EDGE_SELECTED_GLOW": (255, 179, 0, 80),
            "INPUT_BG": "#040406",
            "INPUT_TEXT": "#00E5FF",
            "INPUT_BORDER": "#1E2233",
            "TEXTAREA_BG": "#040406",
            "TEXTAREA_TEXT": "#FFB300",
            "UI_HIGHLIGHT": "#580A4E",
            "UI_HIGHLIGHT_TEXT": "#FFFFFF",
        },
    }

    GRID_SIZE = 25
    NODE_RADIUS = 6.0

    SEMANTIC_DEFAULTS = {
        "RUN_BG": "#16A34A",
        "STOP_BG": "#DC2626",
        "STATUS_RUNNING": "#F59E0B",
        "STATUS_SUCCESS": "#22C55E",
        "STATUS_FAILED": "#EF4444",
        "STATUS_SKIPPED": "#64748B",
        "LOG_INFO": "#38BDF8",
        "LOG_WARN": "#F59E0B",
        "LOG_ERROR": "#EF4444",
        "LOG_SUCCESS": "#22C55E",
        "TEXT_ON_DARK": "#FFFFFF",
        "TEXT_ON_LIGHT": "#111827",
        "GROUP_DEFAULT": "#4488FF",
    }

    CATEGORY_ACCENT_DEFAULTS = {
        "动作": "#F59E0B",
        "AI核心": "#A855F7",
        "逻辑": "#3B82F6",
        "记忆": "#8B5CF6",
        "网络与侦察": "#06B6D4",
        "通知": "#F97316",
        "系统": "#64748B",
        "文本": "#10B981",
        "时间": "#EAB308",
        "触发": "#22C55E",
        "视觉": "#EC4899",
        "General": "#6366F1",
    }

    @classmethod
    def load_global_theme(cls) -> str:
        """从本地磁盘读取全局默认的护城河偏好"""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    saved_theme = data.get("theme", "")
                    if saved_theme in cls.PRESETS:
                        return saved_theme
            except Exception:
                pass  # 就算读取失败也无所谓，直接静默降级

        # 默认回退到字典里的第一个主题 (Command Terminal)
        return list(cls.PRESETS.keys())[0]

    @classmethod
    def load_global_edge_style(cls) -> str:
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    style = json.load(f).get("edge_style", "curve")
                    if style in cls.EDGE_STYLES:
                        return style
            except Exception:
                pass
        return "curve"

    @classmethod
    def _save_preference(cls, key: str, value: str):
        data = {}
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
        except Exception:
            data = {}
        data[key] = value
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception:
            pass

    @classmethod
    def save_global_theme(cls, theme_name: str):
        """将当前活跃的主题刻入全局记忆体"""
        cls._save_preference("theme", theme_name)

    @classmethod
    def save_global_edge_style(cls, edge_style: str):
        if edge_style in cls.EDGE_STYLES:
            cls._save_preference("edge_style", edge_style)

    @classmethod
    def switch_theme(cls, theme_name: str):
        """核心枢纽：动态切换主题字典，更新 QColor，并物理固化配置"""
        # 防呆设计：如果传来的主题名字不存在，强制回退默认
        if theme_name not in cls.PRESETS:
            theme_name = list(cls.PRESETS.keys())[0]

        palette = cls.PRESETS[theme_name]

        # 1. 将字典里的 Hex 字符串全部实例化为高性能的 QColor 对象
        cls.BG_COLOR = QColor(palette["BG_COLOR"])
        cls.SCENE_BG = QColor(palette["SCENE_BG"])
        cls.GRID_COLOR = QColor(palette["GRID_COLOR"])
        cls.NODE_BG = QColor(palette["NODE_BG"])
        cls.NODE_TITLE_BG = QColor(palette["NODE_TITLE_BG"])
        cls.NODE_TITLE_TEXT = QColor(palette.get("NODE_TITLE_TEXT", palette["NODE_TEXT"]))
        cls.NODE_BORDER_DEFAULT = QColor(palette["NODE_BORDER_DEFAULT"])
        cls.NODE_BORDER_SELECTED = QColor(palette["NODE_BORDER_SELECTED"])
        cls.NODE_TEXT = QColor(palette["NODE_TEXT"])
        cls.NODE_TEXT_DIM = QColor(palette["NODE_TEXT_DIM"])
        cls.PORT_BG_DEFAULT = QColor(palette["PORT_BG_DEFAULT"])
        cls.PORT_BG_CONNECTED = QColor(palette["PORT_BG_CONNECTED"])
        cls.PORT_BG_HOVER = QColor(palette["PORT_BG_HOVER"])
        cls.EDGE_DEFAULT = QColor(palette["EDGE_DEFAULT"])
        cls.EDGE_ACTIVE = QColor(palette["EDGE_ACTIVE"])
        cls.EDGE_SELECTED = QColor(palette["EDGE_SELECTED"])
        cls.SURFACE_ALT = QColor(palette.get("SURFACE_ALT", palette["INPUT_BG"]))
        cls.MENU_BG = QColor(palette.get("MENU_BG", palette["NODE_BG"]))
        cls.MENU_TEXT = QColor(palette.get("MENU_TEXT", palette["NODE_TEXT"]))
        cls.MENU_BORDER = QColor(palette.get("MENU_BORDER", palette["INPUT_BORDER"]))
        cls.MENU_SEPARATOR = QColor(
            palette.get("MENU_SEPARATOR", palette["INPUT_BORDER"])
        )
        cls.TOOLTIP_BG = QColor(palette.get("TOOLTIP_BG", palette["NODE_BG"]))
        cls.TOOLTIP_TEXT = QColor(palette.get("TOOLTIP_TEXT", palette["NODE_TEXT"]))
        cls.CONSOLE_BG = QColor(palette.get("CONSOLE_BG", palette["BG_COLOR"]))
        cls.CONSOLE_TEXT = QColor(palette.get("CONSOLE_TEXT", palette["NODE_TEXT"]))
        cls.DISABLED_TEXT = QColor(
            palette.get("DISABLED_TEXT", palette["NODE_TEXT_DIM"])
        )

        for name, default in cls.SEMANTIC_DEFAULTS.items():
            setattr(cls, name, QColor(palette.get(name, default)))
        category_accents = palette.get(
            "CATEGORY_ACCENTS", cls.CATEGORY_ACCENT_DEFAULTS
        )
        cls.CATEGORY_ACCENTS = {
            name: QColor(category_accents.get(name, default))
            for name, default in cls.CATEGORY_ACCENT_DEFAULTS.items()
        }

        r, g, b, a = palette["EDGE_SELECTED_GLOW"]
        cls.EDGE_SELECTED_GLOW = QColor(r, g, b, a)

        # 2. 文本与基础颜色直接保留字符串形式，方便写入 QSS 样式表
        cls.INPUT_BG = palette["INPUT_BG"]
        cls.INPUT_TEXT = palette["INPUT_TEXT"]
        cls.INPUT_BORDER = palette["INPUT_BORDER"]
        cls.TEXTAREA_BG = palette["TEXTAREA_BG"]
        cls.TEXTAREA_TEXT = palette["TEXTAREA_TEXT"]
        cls.UI_HIGHLIGHT = palette["UI_HIGHLIGHT"]
        cls.UI_HIGHLIGHT_TEXT = palette["UI_HIGHLIGHT_TEXT"]

        # 3. 每次发生切换（无论是手动下拉框，还是蓝图加载触发），都同步更新全局记忆体
        cls.save_global_theme(theme_name)

    @classmethod
    def text_on_color(cls, color) -> QColor:
        """Choose a theme-owned foreground for an arbitrary accent color."""
        color = QColor(color)
        luminance = (
            color.red() * 299 + color.green() * 587 + color.blue() * 114
        ) / 1000
        return QColor(cls.TEXT_ON_LIGHT if luminance >= 160 else cls.TEXT_ON_DARK)

    @classmethod
    def menu_stylesheet(cls) -> str:
        """Shared context-menu styling; no caller owns literal text colors."""
        return f"""
            QMenu {{
                background-color: {cls.MENU_BG.name()};
                color: {cls.MENU_TEXT.name()};
                border: 1px solid {cls.MENU_BORDER.name()};
                border-radius: 6px;
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 22px 6px 12px;
                min-width: 110px;
                background-color: transparent;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background-color: {cls.UI_HIGHLIGHT};
                color: {cls.UI_HIGHLIGHT_TEXT};
            }}
            QMenu::item:disabled {{ color: {cls.DISABLED_TEXT.name()}; }}
            QMenu::separator {{
                height: 1px;
                background-color: {cls.MENU_SEPARATOR.name()};
                margin: 4px 6px;
            }}
            QMenu::indicator:checked {{
                background-color: {cls.PORT_BG_HOVER.name()};
                border-radius: 4px;
            }}
        """


# ================= 引擎物理点火 =================
# 在 Python 加载这个模块时，自动触发一次读取，完成初始颜色的装载
Theme.switch_theme(Theme.load_global_theme())
