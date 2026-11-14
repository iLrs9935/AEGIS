from .i18n import (
    QLabel,
    QMenu,
    QPushButton,
    language,
    set_language,
    tr,
)
# ui/main_window.py
import glob
import json
import os
import shutil
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QActionGroup, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.engine import DAGEngine
from core.security import PermissionDenied
from core.workflow import migrate_click_modes, validate_document
from core.event_bus import bus
from nodes import NODE_REGISTRY

from .graph_items import EdgeItem, GroupItem, NodeItem
from .graph_view import AEGISScene, AEGISView
from .node_inspector import NodeInspector
from .theme import Theme

try:
    from functions.func_actions import stop_event
except ImportError:
    stop_event = None


import sys  # 确保顶部导入了 sys


class MainWindow(QMainWindow):
    EDGE_STYLE_LABELS = {
        "曲线": "curve",
        "直角线": "orthogonal",
        "电路板连接": "circuit",
    }

    def __init__(self, init_file=None, autorun=False):
        super().__init__()
        self.setWindowTitle(tr("AEGIS 3.0.1 - 战术指挥终端"))
        self.resize(1400, 900)
        self.setStyleSheet(f"background-color: {Theme.BG_COLOR.name()};")

        self.engine = DAGEngine()
        self.current_workflow_path = None
        self.workflow_source = "local"
        self.workflow_meta = {}
        self.workflow_notices = []
        self.current_theme_name = Theme.load_global_theme()
        self.edge_style = Theme.load_global_edge_style()
        self._inspector_width = 320
        self._pending_workflow_switch = None

        # ================= 修复：智能判断运行环境 =================
        if getattr(sys, "frozen", False):
            # 如果是打包后的 exe 运行，根目录就是 exe 所在的目录
            base_dir = os.path.dirname(sys.executable)
        else:
            # 如果是 python 脚本运行，根目录就是当前文件所在目录的上一级
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

        self.workflow_dir = os.path.join(base_dir, "workflows")
        os.makedirs(self.workflow_dir, exist_ok=True)
        if getattr(sys, "frozen", False):
            # PyInstaller 6 把 datas 放在 _MEIPASS/_internal。首次运行只
            # 补齐缺失模板，绝不覆盖用户已经修改过的同名工作流。
            bundled_workflow_dir = os.path.join(
                getattr(sys, "_MEIPASS", base_dir), "workflows"
            )
        else:
            bundled_workflow_dir = os.path.join(base_dir, "examples", "workflows")
        if os.path.isdir(bundled_workflow_dir):
            for bundled_path in glob.glob(os.path.join(bundled_workflow_dir, "*.json")):
                target_path = os.path.join(self.workflow_dir, os.path.basename(bundled_path))
                if not os.path.exists(target_path):
                    shutil.copy2(bundled_path, target_path)
        # ==========================================================

        self.init_ui()
        bus.log_emitted.connect(self.append_log)
        bus.blueprint_jump_requested.connect(self.handle_blueprint_jump)
        bus.run_blueprint_jump_requested.connect(self._on_run_blueprint_jump)
        bus.dag_completed.connect(self._on_dag_completed)
        bus.run_dag_completed.connect(self._on_run_dag_completed)
        # 处理启动传参（如果传入的是相对路径，需要将其转换为绝对路径）
        if init_file:
            # 兼容绝对路径和相对于 exe 的相对路径
            if not os.path.isabs(init_file):
                init_file = os.path.join(base_dir, init_file)

            if os.path.exists(init_file):
                QTimer.singleShot(
                    500, lambda: self._handle_auto_start(init_file, autorun)
                )

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ================= 顶部控制台 (极简版) =================
        toolbar = QWidget()
        self.toolbar = toolbar  # 存为实例变量，方便后续刷新样式
        toolbar.setFixedHeight(50)
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(10, 0, 15, 0)

        self.btn_toggle_side = QPushButton("◀")
        self.btn_toggle_side.setFixedSize(30, 30)
        self.btn_toggle_side.clicked.connect(self.toggle_sidebar)

        btn_run = QPushButton("▶ 运行")
        self.btn_run = btn_run
        btn_run.clicked.connect(self.compile_and_run_dag)

        btn_stop = QPushButton("⏹ 停止")
        self.btn_stop = btn_stop
        btn_stop.clicked.connect(self.stop_dag)

        self.settings_button = QToolButton()
        self.settings_button.setText("⚙")
        self.settings_button.setToolTip(tr("画布设置"))
        self.settings_button.setFixedSize(34, 34)
        self.settings_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        self.settings_menu = QMenu(self.settings_button)
        theme_menu = self.settings_menu.addMenu("🎨 换皮肤")
        self.theme_action_group = QActionGroup(self)
        self.theme_action_group.setExclusive(True)
        self.theme_actions = {}
        for theme_name in Theme.PRESETS:
            action = theme_menu.addAction(theme_name)
            action.setCheckable(True)
            action.triggered.connect(
                lambda checked=False, name=theme_name: self.on_theme_changed(name)
            )
            self.theme_action_group.addAction(action)
            self.theme_actions[theme_name] = action

        edge_menu = self.settings_menu.addMenu("〽 换连接线")
        self.edge_action_group = QActionGroup(self)
        self.edge_action_group.setExclusive(True)
        self.edge_actions = {}
        for label, style in self.EDGE_STYLE_LABELS.items():
            action = edge_menu.addAction(label)
            action.setCheckable(True)
            action.triggered.connect(
                lambda checked=False, value=style: self.on_edge_style_changed(value)
            )
            self.edge_action_group.addAction(action)
            self.edge_actions[style] = action

        self.background_menu = self.settings_menu.addMenu("🖼️ 画布背景")
        self.load_background_action = self.background_menu.addAction("📂 载入背景图...")
        self.load_background_action.triggered.connect(
            lambda: self.view._load_background_image()
        )
        self.opacity_background_action = self.background_menu.addAction(
            "🎛️ 调整透明度..."
        )
        self.opacity_background_action.triggered.connect(
            lambda: self.view._adjust_background_opacity()
        )
        self.clear_background_action = self.background_menu.addAction("🗑️ 移除背景")
        self.clear_background_action.triggered.connect(
            lambda: self.view._clear_background_image()
        )
        self.settings_button.setMenu(self.settings_menu)
        self._refresh_settings_checks()

        tb_layout.addWidget(self.btn_toggle_side)
        tb_layout.addSpacing(10)
        tb_layout.addWidget(btn_run)
        tb_layout.addWidget(btn_stop)
        tb_layout.addStretch()
        self.language_button = QToolButton()
        self.language_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.language_button.setText("EN" if language() == "en" else "中文")
        self.language_button.setToolTip("Language / 语言")
        self.language_menu = QMenu(self.language_button)
        for code, label in (("en", "English"), ("zh", "简体中文")):
            action = self.language_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(language() == code)
            action.triggered.connect(lambda checked=False, value=code: self.set_ui_language(value))
        self.language_button.setMenu(self.language_menu)
        tb_layout.addWidget(self.language_button)
        tb_layout.addWidget(self.settings_button)
        layout.addWidget(toolbar)

        # ================= 核心工作区 =================
        self.main_h_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_h_splitter.setHandleWidth(2)

        self.sidebar_widget = QWidget()
        sidebar_layout = QVBoxLayout(self.sidebar_widget)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        self.sidebar_header = QLabel(" 📁 工作流")
        sidebar_layout.addWidget(self.sidebar_header)

        self.workflow_list = QListWidget()
        self.workflow_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.workflow_list.itemDoubleClicked.connect(self._on_workflow_double_clicked)

        # 【黑魔法：开启右键菜单拦截】
        self.workflow_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.workflow_list.customContextMenuRequested.connect(
            self.show_workflow_context_menu
        )

        sidebar_layout.addWidget(self.workflow_list)
        self.main_h_splitter.addWidget(self.sidebar_widget)

        self.right_v_splitter = QSplitter(Qt.Orientation.Vertical)
        self.right_v_splitter.setHandleWidth(2)
        self.scene = AEGISScene(edge_style=self.edge_style)
        self.view = AEGISView(self.scene)
        self.right_v_splitter.addWidget(self.view)

        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.right_v_splitter.addWidget(self.console)

        self.right_v_splitter.setSizes([700, 200])
        self.main_h_splitter.addWidget(self.right_v_splitter)

        self.inspector = NodeInspector()
        self.main_h_splitter.addWidget(self.inspector)
        self.main_h_splitter.setStretchFactor(0, 0)
        self.main_h_splitter.setStretchFactor(1, 1)
        self.main_h_splitter.setStretchFactor(2, 0)
        self.inspector.hide()
        self.main_h_splitter.setSizes([200, 1200, 0])
        self.scene.selectionChanged.connect(self._on_scene_selection_changed)
        layout.addWidget(self.main_h_splitter)
        self.refresh_workflow_list()
        self._setup_shortcuts()
        self.apply_theme_styles()

    def set_ui_language(self, chosen, persist=True):
        """Switch presentation in place, preserving the graph and undo history."""
        set_language(chosen, persist=persist)
        self.setWindowTitle(tr("AEGIS 3.0.1 - 战术指挥终端"))
        self.settings_button.setToolTip(tr("画布设置"))
        self.language_button.setText("EN" if chosen == "en" else "中文")
        for action, code in zip(self.language_menu.actions(), ("en", "zh")):
            action.setChecked(chosen == code)
        node = self.inspector.current_node
        if node:
            self.inspector._displayed_node_name = tr(node.name)
            self.inspector.title.setText(self.inspector._displayed_node_name)
        else:
            self.inspector.title.setText(tr("未选择节点"))
        for item in self.scene.items():
            if isinstance(item, NodeItem):
                item._refresh_port_hover_labels()
                for port in item.out_ports:
                    port.setToolTip(tr(port.name))
        self.scene.update()
        self.view.viewport().update()

    def apply_theme_styles(self):
        """核心：统一将 Theme 中的颜色应用到外层 QWidget 控件的 QSS 中"""

        # 1. 主窗口与工具栏背景 (把写死的边框颜色换成 INPUT_BORDER)
        self.setStyleSheet(f"""
            QMainWindow, QDialog, QMessageBox {{
                background-color: {Theme.BG_COLOR.name()};
                color: {Theme.NODE_TEXT.name()};
            }}
            QWidget, QLabel, QCheckBox, QRadioButton {{ color: {Theme.NODE_TEXT.name()}; }}
            QToolTip {{
                background-color: {Theme.TOOLTIP_BG.name()};
                color: {Theme.TOOLTIP_TEXT.name()};
                border: 1px solid {Theme.MENU_BORDER.name()};
                padding: 5px 7px;
            }}
        """)
        self.toolbar.setStyleSheet(
            f"background-color: {Theme.NODE_BG.name()}; border-bottom: 1px solid {Theme.INPUT_BORDER};"
        )

        # 2. 按钮样式
        # (侧边栏收起按钮的 hover 颜色也动态跟着主题的 hover 色走)
        self.btn_toggle_side.setStyleSheet(f"""
            QPushButton {{ background-color: transparent; color: {Theme.NODE_TEXT_DIM.name()}; font-size: 16px; border: none; }}
            QPushButton:hover {{ color: {Theme.NODE_TEXT.name()}; background-color: {Theme.PORT_BG_HOVER.name()}; border-radius: 4px; }}
        """)
        self.btn_run.setStyleSheet(
            f"background-color: {Theme.RUN_BG.name()}; color: {Theme.text_on_color(Theme.RUN_BG).name()}; font-weight: bold; border: none; border-radius: 6px; padding: 8px 15px;"
        )
        self.btn_stop.setStyleSheet(
            f"background-color: {Theme.STOP_BG.name()}; color: {Theme.text_on_color(Theme.STOP_BG).name()}; font-weight: bold; border: none; border-radius: 6px; padding: 8px 15px;"
        )

        # 3. 侧边栏列表 (彻底干掉写死的 #333 边框线)
        self.sidebar_widget.setStyleSheet(
            f"background-color: {Theme.SCENE_BG.name()}; border-right: 1px solid {Theme.INPUT_BORDER};"
        )
        self.sidebar_header.setStyleSheet(
            f"color: {Theme.NODE_TEXT.name()}; font-weight: 700; padding: 10px; background-color: {Theme.SURFACE_ALT.name()}; border: none;"
        )
        self.workflow_list.setStyleSheet(f"""
            QListWidget {{ background-color: {Theme.SCENE_BG.name()}; color: {Theme.NODE_TEXT_DIM.name()}; border: none; font-size: 13px; outline: none; }}
            QListWidget::item {{ padding: 8px; border-bottom: 1px solid {Theme.INPUT_BORDER}; }}
            QListWidget::item:hover {{ background-color: {Theme.NODE_BG.name()}; }}
            QListWidget::item:selected {{ background-color: {Theme.UI_HIGHLIGHT}; color: {Theme.UI_HIGHLIGHT_TEXT}; }}
        """)

        self.settings_button.setStyleSheet(f"""
            QToolButton {{
                background: transparent;
                color: {Theme.NODE_TEXT.name()};
                border: 1px solid {Theme.INPUT_BORDER};
                border-radius: 8px;
                font-size: 18px;
            }}
            QToolButton:hover, QToolButton::menu-button:hover {{
                background: {Theme.INPUT_BG};
                border-color: {Theme.PORT_BG_HOVER.name()};
            }}
            QToolButton::menu-indicator {{ image: none; }}
        """)
        self.settings_menu.setStyleSheet(Theme.menu_stylesheet())

        splitter_style = f"""
            QSplitter {{ border: none; background: {Theme.BG_COLOR.name()}; }}
            QSplitter::handle {{ background-color: {Theme.INPUT_BORDER}; border: none; }}
            QSplitter::handle:hover {{ background-color: {Theme.PORT_BG_HOVER.name()}; }}
            QSplitter::handle:horizontal {{ width: 2px; margin: 0; }}
            QSplitter::handle:vertical {{ height: 2px; margin: 0; }}
        """
        self.main_h_splitter.setStyleSheet(splitter_style)
        self.right_v_splitter.setStyleSheet(splitter_style)

        # 4. 控制台
        self.console.setStyleSheet(
            f"background-color: {Theme.CONSOLE_BG.name()}; color: {Theme.CONSOLE_TEXT.name()}; font-family: Consolas; font-size: 13px; padding: 10px; border: none;"
        )
        self.view.setStyleSheet(
            f"QGraphicsView {{ background-color: {Theme.SCENE_BG.name()}; border: none; outline: none; }}"
        )

        # 5. 更新画布背景
        self.scene.setBackgroundBrush(Theme.SCENE_BG)
        self.inspector.apply_theme()

    def on_theme_changed(self, theme_name):
        """设置菜单切换皮肤时，热更新整个编辑器。"""
        # 1. 改变内核里的色值
        Theme.switch_theme(theme_name)
        self.current_theme_name = theme_name
        self._refresh_settings_checks()

        # 2. 刷新外层 QWidget 控件的样式
        self.apply_theme_styles()

        for item in self.scene.items():
            if isinstance(item, NodeItem) and item.widget:
                item.widget.apply_theme()
            elif isinstance(item, GroupItem):
                item.apply_theme()

        # 4. [黑魔法] 强制刷新画布的绘画(paint)层
        self.view.viewport().update()

        bus.log_emitted.emit(
            "INFO", "System", f"🎨 视网膜神经接入：已切换至【{theme_name}】终端皮肤"
        )

    def on_edge_style_changed(self, edge_style):
        if edge_style not in Theme.EDGE_STYLES:
            edge_style = "curve"
        self.edge_style = edge_style
        self.scene.edge_style = edge_style
        Theme.save_global_edge_style(edge_style)
        for item in self.scene.items():
            if isinstance(item, EdgeItem):
                item.set_style(edge_style)
        self._refresh_settings_checks()
        self.view.viewport().update()
        label = next(
            (
                name
                for name, value in self.EDGE_STYLE_LABELS.items()
                if value == edge_style
            ),
            "曲线",
        )
        bus.log_emitted.emit("INFO", "UI", f"〽 连接线已切换为：{label}")

    def _refresh_settings_checks(self):
        for name, action in getattr(self, "theme_actions", {}).items():
            action.setChecked(name == self.current_theme_name)
        for style, action in getattr(self, "edge_actions", {}).items():
            action.setChecked(style == self.edge_style)

    def _setup_shortcuts(self):
        """统一配置系统的全局快捷键"""
        self.shortcuts = []

        def register(sequence, callback):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)
            self.shortcuts.append(shortcut)

        # 1. 保存当前图纸 (Ctrl + S)
        register("Ctrl+S", self.save_graph_to_json)

        # 2. 运行战术终端 (F5)
        register("F5", self.compile_and_run_dag)

        # 3. 紧急停止 (Shift + F5)
        register("Shift+F5", self.stop_dag)

        # 4. 切换侧边栏 (Ctrl + B)
        register("Ctrl+B", self.toggle_sidebar)

    # ================= 动作逻辑 =================
    def toggle_sidebar(self):
        if not self.sidebar_widget.isHidden():
            self.sidebar_widget.hide()
            self.btn_toggle_side.setText("▶")
        else:
            self.sidebar_widget.show()
            sizes = self.main_h_splitter.sizes()
            inspector_width = 0 if self.inspector.isHidden() else self._inspector_width
            self.main_h_splitter.setSizes(
                [200, max(300, sum(sizes) - 200 - inspector_width), inspector_width]
            )
            self.btn_toggle_side.setText("◀")

    def _set_inspector_visible(self, visible):
        sizes = self.main_h_splitter.sizes()
        left_width = 0 if self.sidebar_widget.isHidden() else max(180, sizes[0])
        total_width = max(sum(sizes), self.main_h_splitter.width())
        if visible:
            if not self.inspector.isHidden():
                return
            self.inspector.show()
            center_width = max(
                300, total_width - left_width - self._inspector_width
            )
            self.main_h_splitter.setSizes(
                [left_width, center_width, self._inspector_width]
            )
        else:
            if self.inspector.isHidden():
                return
            if sizes[2] > 0:
                self._inspector_width = sizes[2]
            self.inspector.hide()
            self.main_h_splitter.setSizes(
                [left_width, max(300, total_width - left_width), 0]
            )

    def _on_scene_selection_changed(self):
        selected = self.scene.selectedItems()
        if len(selected) == 1 and isinstance(selected[0], NodeItem):
            self._set_inspector_visible(True)
            self.inspector.show_node(selected[0])
        else:
            self.inspector.show_empty()
            self._set_inspector_visible(False)

    def refresh_workflow_list(self):
        self.workflow_list.clear()
        files = glob.glob(os.path.join(self.workflow_dir, "*.json"))
        for f in sorted(files):
            self.workflow_list.addItem(os.path.basename(f))

    def _on_workflow_double_clicked(self, item):
        self._request_workflow_switch(
            os.path.join(self.workflow_dir, item.text()), autorun=False
        )

    # ================= 强大的右键上下文菜单 =================
    def show_workflow_context_menu(self, pos):
        item = self.workflow_list.itemAt(pos)
        menu = QMenu(self)
        menu.setStyleSheet(Theme.menu_stylesheet())

        action_new = menu.addAction("📄 新建空白图纸")
        action_save = menu.addAction("💾 保存当前图纸")
        menu.addSeparator()
        action_import = menu.addAction("📥 导入外部图纸")

        if item:
            action_export = menu.addAction("📤 导出该图纸")
            menu.addSeparator()
            action_delete = menu.addAction("🗑️ 删除该图纸")
        else:
            action_export, action_delete = None, None

        action = menu.exec(self.workflow_list.mapToGlobal(pos))

        if action == action_new:
            self._request_workflow_switch(None, autorun=False)
        elif action == action_save:
            # 如果点在了某个文件上，直接覆盖它；否则弹出保存框
            if item:
                self.save_graph_to_json(os.path.join(self.workflow_dir, item.text()))
            else:
                self.save_graph_to_json()
        elif action == action_import:
            file_path, _ = QFileDialog.getOpenFileName(
                self, tr("导入外部图纸"), tr(""), "JSON (*.json)"
            )
            if file_path:
                target = os.path.join(self.workflow_dir, os.path.basename(file_path))
                shutil.copy(file_path, target)
                self.refresh_workflow_list()
                self._request_workflow_switch(target, autorun=False)
                bus.log_emitted.emit(
                    "SUCCESS",
                    "System",
                    f"📥 已导入并加载: {os.path.basename(file_path)}",
                )
        elif action == action_export and action_export:
            source = os.path.join(self.workflow_dir, item.text())
            target, _ = QFileDialog.getSaveFileName(
                self, tr("导出至..."), tr(item.text()), "JSON (*.json)"
            )
            if target:
                shutil.copy(source, target)
                bus.log_emitted.emit("SUCCESS", "System", f"📤 图纸已导出至: {target}")
        elif action == action_delete and action_delete:
            reply = QMessageBox.question(
                self,
                tr("危险操作"),
                tr(f"确定要永久删除 {item.text()} 吗？"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                deleted_path = os.path.abspath(
                    os.path.join(self.workflow_dir, item.text())
                )
                os.remove(deleted_path)
                if self.current_workflow_path == deleted_path:
                    self.current_workflow_path = None
                self.refresh_workflow_list()
                bus.log_emitted.emit("WARN", "System", f"🗑️ 已删除图纸: {item.text()}")

    # ================= 序列化 =================
    def save_graph_to_json(self, target_path=None):
        if target_path is None:
            target_path = self.current_workflow_path
        if not target_path:
            target_path, _ = QFileDialog.getSaveFileName(
                self, tr("保存为"), tr(self.workflow_dir), "JSON (*.json)"
            )
        if not target_path:
            return

        # 加入 meta 基因序列，记录当前终端皮肤
        data = {
            "meta": {
                **self.workflow_meta,
                "source": self.workflow_source,
                "click_mode_version": 1,
                "theme": self.current_theme_name,
                "edge_style": self.edge_style,
            },
            "nodes": [],
            "groups": [],
            "edges": [],
        }
        for item in self.scene.items():
            if isinstance(item, NodeItem):
                data["nodes"].append(
                    {
                        "id": item.id,
                        "type": getattr(item, "node_type", item.name),
                        "name": item.name,
                        "category": getattr(item, "category", "General"),
                        "display_mode": getattr(item, "display_mode", "standard"),
                        "x": item.pos().x(),
                        "y": item.pos().y(),
                        "w": item.width,
                        "h": item.height,
                        "_expanded_height": item._expanded_height,
                        "config": item.get_config(),
                        "signal_config": item.get_signal_config(),
                        "is_disabled": item.is_disabled,
                        "is_collapsed": getattr(item, "is_collapsed", False),
                    }
                )
            elif isinstance(item, GroupItem):
                data["groups"].append(
                    {
                        "id": item.id,
                        "name": item.name,
                        "x": item.pos().x(),
                        "y": item.pos().y(),
                        "w": item.width,
                        "h": item._expanded_height,
                        "is_disabled": not item.toggle_cb.isChecked(),
                        "is_collapsed": getattr(item, "is_collapsed", False),
                        "is_locked": getattr(item, "is_locked", False),
                        "color": item.get_group_color(),
                        "member_ids": [
                            node.id
                            for node in getattr(item, "contained_nodes", [])
                            if isinstance(node, NodeItem)
                            and node.scene() is self.scene
                        ],
                    }
                )

        for conn in self.scene.connections:
            in_port, out_port, _ = conn
            data["edges"].append(
                {
                    "src_id": out_port.parentItem().id,
                    "src_port": out_port.name,
                    "tgt_id": in_port.parentItem().id,
                    "tgt_port": in_port.name,
                }
            )

        try:
            with open(target_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            self.current_workflow_path = os.path.abspath(target_path)
            bus.log_emitted.emit(
                "SUCCESS", "System", f"💾 图纸已保存: {os.path.basename(target_path)}"
            )
            self.refresh_workflow_list()
        except Exception as e:
            bus.log_emitted.emit("ERROR", "System", f"保存失败: {e}")

    def load_graph_from_json(self, file_path):
        if self.engine.is_running:
            bus.log_emitted.emit("ERROR", "Security", "Cannot replace a running workflow")
            return False
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            validate_document(data, NODE_REGISTRY)
        except Exception as e:
            bus.log_emitted.emit("ERROR", "System", f"读取失败: {e}")
            return False

        data, self.workflow_notices = migrate_click_modes(data)
        for notice in self.workflow_notices:
            bus.log_emitted.emit("WARN", "Migration", notice)
        self.workflow_meta = dict(data.get("meta", {}))
        # A file cannot grant itself local trust or deserialize permissions.
        self.workflow_source = "ai" if self.workflow_meta.get("source") == "ai" else "external"
        data = self._migrate_legacy_value_workflow(data)

        self.scene.clear()
        self.scene.connections = []
        node_map = {}

        # ================= 蓝图视觉基底还原 =================
        meta = data.get("meta", {})
        saved_theme = meta.get("theme")
        saved_edge_style = meta.get("edge_style")

        # 如果图纸里有记录主题，且主题存在于注册表中
        if saved_theme and saved_theme in Theme.PRESETS:
            self.on_theme_changed(saved_theme)
        if saved_edge_style in Theme.EDGE_STYLES:
            self.on_edge_style_changed(saved_edge_style)
        # =========================================================

        for g_data in data.get("groups", []):
            self.view._create_group_from_data(g_data)

        for n_data in data.get("nodes", []):
            node = self.view._create_node_from_data(n_data)
            if node:
                node_map[n_data["id"]] = node

        # 逻辑组必须等节点全部恢复后再落实折叠，否则无法记住并隐藏组内节点。
        for item in self.scene.items():
            if isinstance(item, GroupItem):
                self.view._finalize_group_state(item, node_map)

        for e_data in data.get("edges", []):
            src_node = node_map.get(e_data["src_id"])
            tgt_node = node_map.get(e_data["tgt_id"])
            if src_node and tgt_node:
                src_port = next(
                    (p for p in src_node.out_ports if p.name == e_data["src_port"]),
                    None,
                )
                tgt_port = tgt_node.in_port
                if src_port and tgt_port:
                    edge = EdgeItem(
                        src_port.scenePos(),
                        tgt_port.scenePos(),
                        style=self.edge_style,
                    )
                    edge.set_endpoint_colors(
                        src_node.category_color, tgt_node.category_color
                    )
                    self.scene.addItem(edge)
                    self.scene.connections.append((tgt_port, src_port, edge))
                    src_port.set_connected(True)
                    tgt_port.set_connected(True)
                    edge.update_path(src_port.scenePos(), tgt_port.scenePos())

        bus.log_emitted.emit(
            "SUCCESS", "System", f"📂 工作流加载就绪: {os.path.basename(file_path)}"
        )
        self.current_workflow_path = os.path.abspath(file_path)
        self.view.reset_history()
        return True

    @staticmethod
    def _migrate_legacy_value_workflow(data):
        """Insert an explicit router for old two-port vision branches.

        Migration is in-memory. Saving the workflow persists the new,
        single-value representation.
        """
        nodes = list(data.get("nodes", []))
        edges = list(data.get("edges", []))
        known_ids = {str(node.get("id")) for node in nodes}
        migrated_nodes = []
        migrated_edges = list(edges)

        for vision in nodes:
            node_type = vision.get("type", vision.get("name"))
            if node_type != "视觉寻图":
                continue
            vision_id = str(vision.get("id"))
            legacy_edges = [
                edge
                for edge in migrated_edges
                if edge.get("src_id") == vision_id
                and edge.get("src_port") in {"找到目标", "未找到"}
            ]
            if not legacy_edges:
                continue

            router_id = f"legacy-value-router-{vision_id}"
            suffix = 1
            while router_id in known_ids:
                router_id = f"legacy-value-router-{vision_id}-{suffix}"
                suffix += 1
            known_ids.add(router_id)
            router_node = {
                "id": router_id,
                "type": "信号分流器",
                "name": "寻图结果分流",
                "category": "逻辑",
                "display_mode": "standard",
                "x": float(vision.get("x", 0)) + 250,
                "y": float(vision.get("y", 0)),
                "config": {
                    "节点标签": "寻图结果分流",
                    "输入选择": "最后一个",
                    "匹配模式": "首个匹配",
                    "路由规则": [
                        {
                            "port": "找到目标",
                            "path": "found",
                            "operator": "等于",
                            "target": "true",
                        },
                        {
                            "port": "未找到",
                            "path": "found",
                            "operator": "等于",
                            "target": "false",
                        },
                    ],
                    "未匹配时": "终止工作流",
                    "默认出口名称": "默认",
                },
                "signal_config": {
                    "outputs": {
                        "找到目标": {"value": ""},
                        "未找到": {"value": ""},
                    },
                    "input": {"type": "object", "required": True},
                },
                "is_disabled": False,
                "is_collapsed": False,
            }
            migrated_nodes.append(router_node)
            for edge in legacy_edges:
                edge["src_id"] = router_id
            migrated_edges.append(
                {
                    "src_id": vision_id,
                    "src_port": "OUT",
                    "tgt_id": router_id,
                    "tgt_port": "IN",
                }
            )

        if migrated_nodes:
            data = dict(data)
            data["nodes"] = nodes + migrated_nodes
            data["edges"] = migrated_edges
        return data

    # ================= 引擎调度 =================
    def _handle_auto_start(self, file_path, autorun):
        self._request_workflow_switch(
            file_path, autorun=autorun, start_delay_ms=3000
        )

    def _request_workflow_switch(
        self, file_path, autorun=False, start_delay_ms=0
    ):
        """切换画布；若旧 DAG 尚未结束，先等待其完成取消。"""
        if file_path and not os.path.isabs(file_path):
            file_path = os.path.join(self.workflow_dir, os.path.basename(file_path))
        if file_path:
            file_path = os.path.abspath(file_path)

        request = (file_path, bool(autorun), max(0, int(start_delay_ms)))
        if self.engine.is_running:
            self._pending_workflow_switch = request
            if stop_event:
                stop_event.set()
            target_name = os.path.basename(file_path) if file_path else "空白图纸"
            bus.log_emitted.emit(
                "WARN",
                "System",
                f"⏳ 正在停止旧工作流，停稳后切换至: {target_name}",
            )
            return False

        self._pending_workflow_switch = None
        return self._apply_workflow_switch(*request)

    def _apply_workflow_switch(self, file_path, autorun, start_delay_ms):
        if file_path:
            if not self.load_graph_from_json(file_path):
                return False
        else:
            self.scene.clear()
            self.scene.connections = []
            self.current_workflow_path = None
            self.workflow_source = "local"
            self.workflow_meta = {}
            self.workflow_notices = []
            self.view.reset_history()
            self.console.clear()
            bus.log_emitted.emit("INFO", "System", "✨ 图纸已清空，开启全新部署。")

        if autorun:
            QTimer.singleShot(start_delay_ms, self.compile_and_run_dag)
        return True

    def _on_dag_completed(self, _reason, _success):
        if self.engine._managed:
            return  # Public completion events are display/legacy notifications.
        self._finish_workflow_switch()

    def _on_run_dag_completed(self, run_id, _reason, _success):
        if run_id == self.engine.run_id:
            self._finish_workflow_switch()

    def _finish_workflow_switch(self):
        request = self._pending_workflow_switch
        if request is None:
            return
        self._pending_workflow_switch = None
        self._apply_workflow_switch(*request)

    # ================= 蓝图跃迁核心逻辑 =================
    def _on_run_blueprint_jump(self, run_id, file_path):
        if run_id == self.engine.run_id and self.engine.is_running:
            self.handle_blueprint_jump(file_path)

    def handle_blueprint_jump(self, file_path):
        bus.log_emitted.emit("WARN", "System", "🌀 跃迁引擎介入，当前世界线强制收束...")
        self._request_workflow_switch(file_path, autorun=True)

    def compile_and_run_dag(self):
        # Never clear the shared stop flag or replace the live graph while an
        # older worker is still running. This was the cause of overlapping DAGs
        # and duplicate game launches.
        if self.engine.is_running:
            bus.log_emitted.emit(
                "WARN",
                "Engine",
                "⛔ 当前工作流尚未结束：重复点击运行已拦截。如需重跑，请先停止并等待“工作流已完全停止”。",
            )
            return

        if stop_event:
            stop_event.clear()
        bus.log_emitted.emit("INFO", "Engine", "=" * 40)

        nodes_data = {}
        for item in self.scene.items():
            if isinstance(item, NodeItem):
                item.set_exec_status("Idle")
                nodes_data[item.id] = {
                    "name": getattr(item, "node_type", item.name),
                    "config": item.get_config(),
                    "signal_config": item.get_signal_config(),
                    "is_disabled": item.is_disabled,
                }

        edges_data = [
            (out_p.parentItem().id, out_p.name, in_p.parentItem().id, in_p.name)
            for in_p, out_p, _ in self.scene.connections
        ]

        self.engine.load_from_ui(nodes_data, edges_data, source=self.workflow_source)
        review = self.engine.review_execution()
        if review.unknown:
            bus.log_emitted.emit("ERROR", "Security", review.describe())
            return False
        from functions import func_system
        if review.required and not func_system.SAFE_POWER_MODE:
            if not self._confirm_execution_review(review):
                bus.log_emitted.emit("WARN", "Security", "Execution authorization declined / 已拒绝执行授权")
                return False
            self.engine.authorize_execution(review.required)
        bus.log_emitted.emit("INFO", "Engine", f"开始工作流: {self.current_workflow_path}; 节点={len(nodes_data)}, 连线={len(edges_data)}")
        return self.engine.start_execution()

    def _confirm_execution_review(self, review):
        message = "\n".join([*self.workflow_notices, review.describe()])
        answer = QMessageBox.warning(
            self, "Execution review / 执行安全审查", message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def stop_dag(self):
        if stop_event and self.engine.is_running:
            stop_event.set()
            bus.log_emitted.emit("ERROR", "System", "🛑 人工介入：紧急刹车！")
        else:
            bus.log_emitted.emit("INFO", "System", "当前没有正在执行的工作流。")

    def closeEvent(self, event):
        if self.engine.is_running and stop_event:
            stop_event.set()
        super().closeEvent(event)

    def append_log(self, level, module, message):
        from html import escape
        colors = {
            "INFO": Theme.LOG_INFO.name(),
            "WARN": Theme.LOG_WARN.name(),
            "ERROR": Theme.LOG_ERROR.name(),
            "SUCCESS": Theme.LOG_SUCCESS.name(),
        }
        color = colors.get(level, Theme.CONSOLE_TEXT.name())

        # 获取当前时间戳
        ts = datetime.now().strftime("%H:%M:%S")

        # 将时间戳拼接到 UI 日志中
        html_msg = (
            f'<span style="color: {color};"><b>[{ts}] [{escape(tr(module))}]</b> {escape(tr(message))}</span>'
        )

        self.console.append(html_msg)
        self.console.verticalScrollBar().setValue(
            self.console.verticalScrollBar().maximum()
        )
