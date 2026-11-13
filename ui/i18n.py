"""Presentation-only localization; workflow identifiers always stay canonical."""

import json
import os
import re
import weakref

from PyQt6 import QtGui, QtWidgets
from PyQt6.QtCore import Qt

from core.config import application_directory
from .translations import ENGLISH


_language = "zh"
_controls = weakref.WeakSet()
_CANONICAL_ROLE = int(Qt.ItemDataRole.UserRole) + 42
_REVERSE = {value: key for key, value in ENGLISH.items()}
_PATTERNS = [
    (r"参数 · (?P<count>\d+)", "Parameters · {count}"),
    (r"已选择 (?P<count>\d+) 项", "{count} selected"),
    (r"已选择 (?P<count>\d+) 个图元。可进行复制、删除或建立逻辑组。", "{count} items selected. Copy, delete or group them."),
    (r"🔒 将选中的 (?P<count>\d+) 个节点建立为锁定组", "Create a locked group from {count} selected nodes"),
    (r"✏️ 重命名(?P<kind>.+)", "Rename {kind}"),
    (r"🗑️ 删除(?P<kind>.+)", "Delete {kind}"),
    (r"请输入新(?P<kind>.+)名称:", "New {kind} name:"),
    (r"确定要永久删除 (?P<file>.+) 吗？", "Permanently delete {file}?"),
    (r"分支(?P<number>\d+)", "Branch {number}"),
    (r"📂 工作流加载就绪: (?P<file>.+)", "Workflow loaded: {file}"),
    (r"开始工作流: (?P<file>.+)", "Starting workflow: {file}"),
    (r"💾 图纸已保存: (?P<file>.+)", "Workflow saved: {file}"),
    (r"📤 图纸已导出至: (?P<file>.+)", "Workflow exported: {file}"),
    (r"📥 已导入并加载: (?P<file>.+)", "Imported and loaded: {file}"),
    (r"🗑️ 已删除图纸: (?P<file>.+)", "Workflow deleted: {file}"),
    (r"⏳ 正在停止旧工作流，停稳后切换至: (?P<file>.+)", "Stopping the current workflow before switching to {file}"),
    (r"〽 连接线已切换为：(?P<style>.+)", "Connection style: {style}"),
    (r"🎨 视网膜神经接入：已切换至【(?P<theme>.+)】终端皮肤", "Theme: {theme}"),
    (r"(?P<arrow>[▼▶]) (?P<title>.+)", "{arrow} {title}"),
]


def tr(text):
    if _language == "zh" or not isinstance(text, str):
        return text
    if text in ENGLISH:
        return ENGLISH[text]
    for pattern, template in _PATTERNS:
        matched = re.fullmatch(pattern, text)
        if matched:
            return template.format(**{key: ENGLISH.get(value, value) for key, value in matched.groupdict().items()})
    return text


def language():
    return _language


def initialize_language(requested=None):
    chosen = requested or os.environ.get("AEGIS_LANGUAGE")
    if not chosen:
        try:
            chosen = json.loads((application_directory() / "aegis_settings.json").read_text(encoding="utf-8")).get("language")
        except (OSError, ValueError, AttributeError):
            pass
    set_language(chosen if chosen in {"en", "zh"} else "en")


def set_language(chosen, persist=False):
    global _language
    if chosen not in {"en", "zh"}:
        raise ValueError("Language must be en or zh")
    _language = chosen
    for control in list(_controls):
        try:
            control.retranslate()
        except RuntimeError:
            # Qt may already have destroyed an object owned by a closed menu.
            pass
    if persist:
        path = application_directory() / "aegis_settings.json"
        try:
            settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            if not isinstance(settings, dict):
                settings = {}
            settings["language"] = chosen
            path.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except (OSError, ValueError):
            pass


class _TextControl:
    def setText(self, text):
        self._source_text = _REVERSE.get(text, text) if _language == "en" else text
        super().setText(tr(text))

    def setToolTip(self, text):
        self._source_tooltip = _REVERSE.get(text, text) if _language == "en" else text
        super().setToolTip(tr(text))

    def retranslate(self):
        super().setText(tr(self._source_text))
        if hasattr(self, "_source_tooltip"):
            super().setToolTip(tr(self._source_tooltip))

    def _register(self):
        self._source_text = self.text()
        _controls.add(self)
        self.retranslate()


class QLabel(_TextControl, QtWidgets.QLabel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._register()


class QPushButton(_TextControl, QtWidgets.QPushButton):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._register()


class QCheckBox(_TextControl, QtWidgets.QCheckBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._register()


class QAction(_TextControl, QtGui.QAction):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._register()


class QMenu(QtWidgets.QMenu):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._source_title = self.title()
        _controls.add(self)
        self.retranslate()

    def retranslate(self):
        self.setTitle(tr(self._source_title))

    def addMenu(self, title):
        menu = QMenu(title, self) if isinstance(title, str) else title
        super().addMenu(menu)
        return menu

    def addAction(self, *args):
        if args and isinstance(args[0], str):
            action = QAction(args[0], self)
            super().addAction(action)
            if len(args) > 1 and callable(args[1]):
                action.triggered.connect(args[1])
            return action
        return super().addAction(*args)


class QComboBox(QtWidgets.QComboBox):
    """Translated item text, with the original value returned to node code."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _controls.add(self)

    def addItem(self, text, userData=None):
        super().addItem(tr(text), userData)
        self.setItemData(self.count() - 1, text, _CANONICAL_ROLE)

    def addItems(self, texts):
        for text in texts:
            self.addItem(text)

    def currentText(self):
        value = self.itemData(self.currentIndex(), _CANONICAL_ROLE)
        return value if value is not None else super().currentText()

    def setCurrentText(self, text):
        index = self.findData(text, _CANONICAL_ROLE)
        if index >= 0:
            self.setCurrentIndex(index)
        else:
            super().setCurrentText(text)

    def retranslate(self):
        blocked = self.blockSignals(True)
        try:
            for index in range(self.count()):
                source = self.itemData(index, _CANONICAL_ROLE)
                if source is not None:
                    super().setItemText(index, tr(source))
        finally:
            self.blockSignals(blocked)


class QLineEdit(QtWidgets.QLineEdit):
    """Translate hints only; editable user content is never transformed."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._source_placeholder = ""
        self._source_tooltip = ""
        _controls.add(self)

    def setPlaceholderText(self, text):
        self._source_placeholder = _REVERSE.get(text, text) if _language == "en" else text
        super().setPlaceholderText(tr(text))

    def setToolTip(self, text):
        self._source_tooltip = _REVERSE.get(text, text) if _language == "en" else text
        super().setToolTip(tr(text))

    def retranslate(self):
        super().setPlaceholderText(tr(self._source_placeholder))
        super().setToolTip(tr(self._source_tooltip))
