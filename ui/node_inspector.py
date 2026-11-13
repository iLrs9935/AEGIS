from .i18n import (
    QCheckBox,
    QComboBox,
    QLabel,
    QPushButton,
    QLineEdit,
    tr,
)
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .theme import Theme


class NodeInspector(QWidget):
    """n8n-style right-side configuration panel for the selected node."""

    MODE_LABELS = {
        "纯图标": "icon",
        "标准卡片": "standard",
    }
    MODE_NAMES = {value: key for key, value in MODE_LABELS.items()}
    VALUE_TYPE_LABELS = {
        "任意值": "any",
        "布尔值": "boolean",
        "数字": "number",
        "文本": "string",
        "对象": "object",
        "数组": "array",
        "空值": "null",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_node = None
        self._active_form = None
        self._loading_signal_controls = False
        self.setMinimumWidth(290)
        self.setMaximumWidth(460)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.header = QFrame()
        self.header.setObjectName("inspectorHeader")
        header_layout = QVBoxLayout(self.header)
        header_layout.setContentsMargins(20, 18, 20, 16)
        header_layout.setSpacing(7)

        self.eyebrow = QLabel("NODE CONFIGURATION")
        self.title = QLineEdit("未选择节点")
        self.title.setObjectName("nodeNameEditor")
        self.title.setFrame(False)
        self.title.setReadOnly(True)
        self.title.setToolTip(tr("单击即可修改画布上的节点名称"))
        self.title.editingFinished.connect(self._commit_node_name)

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        self.icon_badge = QLabel("•")
        self.icon_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_badge.setFixedSize(30, 30)
        self.category = QLabel("在画布中选择一个节点")
        meta_row.addWidget(self.icon_badge)
        meta_row.addWidget(self.category)
        meta_row.addStretch()

        header_layout.addWidget(self.eyebrow)
        header_layout.addWidget(self.title)
        header_layout.addLayout(meta_row)
        root.addWidget(self.header)

        self.controls = QFrame()
        self.controls.setObjectName("inspectorControls")
        controls_layout = QVBoxLayout(self.controls)
        controls_layout.setContentsMargins(20, 14, 20, 14)
        controls_layout.setSpacing(8)

        mode_label = QLabel("画布显示")
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(self.MODE_LABELS.keys())
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)
        self.toggle_disabled = QPushButton("禁用节点")
        self.toggle_disabled.clicked.connect(self._toggle_disabled)
        self.mode_hint = QLabel("双击节点也可以快速切换图标/标准模式")
        self.mode_hint.setWordWrap(True)

        controls_layout.addWidget(mode_label)
        controls_layout.addWidget(self.mode_combo)
        controls_layout.addWidget(self.toggle_disabled)
        controls_layout.addWidget(self.mode_hint)
        root.addWidget(self.controls)

        self.routing_panel = QFrame()
        self.routing_panel.setObjectName("signalRoutingPanel")
        routing_layout = QVBoxLayout(self.routing_panel)
        routing_layout.setContentsMargins(20, 14, 20, 14)
        routing_layout.setSpacing(7)

        self.routing_title = QLabel("信号路由")
        self.routing_help = QLabel(
            "边上只传递一个 value。输入类型不合法时，本次工作流会立即停止。"
        )
        self.routing_help.setWordWrap(True)
        routing_layout.addWidget(self.routing_title)
        routing_layout.addWidget(self.routing_help)

        output_port_label = QLabel("正在配置的输出点")
        self.output_port_combo = QComboBox()
        self.output_port_combo.currentTextChanged.connect(
            self._on_output_port_changed
        )
        routing_layout.addWidget(output_port_label)
        routing_layout.addWidget(self.output_port_combo)

        self.output_value = QLineEdit()
        self.output_value.setPlaceholderText(tr("留空使用节点结果；可填 true、5、文本或对象"))
        self.output_value.textChanged.connect(self._on_signal_routing_changed)
        routing_layout.addWidget(QLabel("value 覆盖值（可选）"))
        routing_layout.addWidget(self.output_value)

        self.input_type = QComboBox()
        self.input_type.addItems(self.VALUE_TYPE_LABELS.keys())
        self.input_type.currentTextChanged.connect(self._on_signal_routing_changed)
        routing_layout.addWidget(QLabel("接收 value 类型"))
        routing_layout.addWidget(self.input_type)

        self.input_required = QCheckBox("必须收到非 null 的上游 value")
        self.input_required.stateChanged.connect(self._on_signal_routing_changed)
        routing_layout.addWidget(self.input_required)

        self.section_label = QLabel("参数")
        self.section_label.setContentsMargins(20, 14, 20, 4)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.form_host = QWidget()
        self.form_layout = QVBoxLayout(self.form_host)
        self.form_layout.setContentsMargins(0, 0, 0, 20)
        self.form_layout.setSpacing(0)
        self.form_layout.addWidget(self.routing_panel)
        self.form_layout.addWidget(self.section_label)
        self.form_layout.addStretch()
        self.scroll.setWidget(self.form_host)
        root.addWidget(self.scroll, 1)

        self.empty_label = QLabel("选择节点后，这里会显示它的全部配置。")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.form_layout.insertWidget(2, self.empty_label)

        self.apply_theme()
        self.show_empty()

    def _detach_form(self):
        if self._active_form:
            self.form_layout.removeWidget(self._active_form)
            self._active_form.hide()
            self._active_form.setParent(None)
            self._active_form = None

    def show_empty(self, message="选择节点后，这里会显示它的全部配置。"):
        self._detach_form()
        self.current_node = None
        self.title.blockSignals(True)
        self.title.setText(tr("未选择节点"))
        self.title.setReadOnly(True)
        self.title.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.title.blockSignals(False)
        self.category.setText("在画布中选择一个节点")
        self.icon_badge.setText("•")
        self.empty_label.setText(message)
        self.empty_label.show()
        self.controls.setEnabled(False)
        self.routing_panel.setEnabled(False)
        self.section_label.setText("参数")

    def show_selection(self, count):
        self.show_empty(f"已选择 {count} 个图元。可进行复制、删除或建立逻辑组。")
        self.title.setText(f"已选择 {count} 项")
        self.category.setText("MULTI SELECTION")

    def show_node(self, node):
        if self.current_node is node:
            self.refresh_node_state()
            return

        self._detach_form()
        self.current_node = node
        self.empty_label.hide()
        self.controls.setEnabled(True)
        self.routing_panel.setEnabled(True)
        self.title.blockSignals(True)
        self._displayed_node_name = tr(node.name)
        self.title.setText(self._displayed_node_name)
        self.title.setReadOnly(False)
        self.title.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.title.blockSignals(False)
        self.category.setText(node.category)
        self.icon_badge.setText(node.category_icon)
        self.section_label.setText(f"参数 · {len(node.config_schema)}")

        self.mode_combo.blockSignals(True)
        self.mode_combo.setCurrentText(
            self.MODE_NAMES.get(node.display_mode, "标准卡片")
        )
        self.mode_combo.blockSignals(False)
        try:
            node.signals.ports_changed.connect(
                self._on_node_ports_changed, Qt.ConnectionType.UniqueConnection
            )
        except (TypeError, RuntimeError):
            pass
        self._load_signal_routing(node)

        if node.widget:
            self._active_form = node.widget
            self.form_layout.insertWidget(2, node.widget)
            node.widget.show()
        else:
            self.empty_label.setText("这个节点没有可配置参数。")
            self.empty_label.show()
        self.refresh_node_state()

    def refresh_node_state(self):
        if not self.current_node:
            return
        node = self.current_node
        self.toggle_disabled.setText("启用节点" if node.is_disabled else "禁用节点")
        badge_text = Theme.text_on_color(node.category_color).name()
        self.icon_badge.setStyleSheet(
            f"background: {node.category_color.name()}; color: {badge_text}; border-radius: 9px; font-weight: 800;"
        )

    def _on_mode_changed(self, label):
        if self.current_node:
            self.current_node.set_display_mode(
                self.MODE_LABELS.get(self.mode_combo.currentText(), "standard")
            )

    def _commit_node_name(self):
        """Commit the editable inspector title back to the canvas node."""
        if not self.current_node:
            return
        new_name = self.title.text().strip()
        if new_name == getattr(self, "_displayed_node_name", None):
            return
        if not new_name:
            self.title.setText(tr(self.current_node.name))
            return
        if new_name == self.current_node.name:
            return
        self.current_node.name = new_name
        self.current_node.update()
        if self.current_node.scene():
            self.current_node.scene().update(self.current_node.sceneBoundingRect())

    def _toggle_disabled(self):
        if self.current_node:
            self.current_node.set_disabled(not self.current_node.is_disabled)
            self.refresh_node_state()

    def _load_signal_routing(self, node):
        config = node.get_signal_config()
        input_config = config.get("input", {})
        type_names = {value: label for label, value in self.VALUE_TYPE_LABELS.items()}

        self._loading_signal_controls = True
        try:
            previous_port = self.output_port_combo.currentText()
            self.output_port_combo.clear()
            self.output_port_combo.addItems(node.out_ports_names)
            if previous_port in node.out_ports_names:
                self.output_port_combo.setCurrentText(previous_port)
            self.input_type.setCurrentText(
                type_names.get(input_config.get("type", "any"), "任意值")
            )
            self.input_required.setChecked(bool(input_config.get("required", False)))
        finally:
            self._loading_signal_controls = False
        self._load_selected_output_config()

    def _load_selected_output_config(self):
        if not self.current_node:
            return
        port_name = self.output_port_combo.currentText()
        output = self.current_node.get_signal_config().get("outputs", {}).get(
            port_name, {}
        )

        self._loading_signal_controls = True
        try:
            self.output_value.setText(output.get("value", ""))
        finally:
            self._loading_signal_controls = False

    def _on_output_port_changed(self, *_):
        if not self._loading_signal_controls:
            self._load_selected_output_config()

    def _on_node_ports_changed(self, node_id):
        if self.current_node and self.current_node.id == node_id:
            self._load_signal_routing(self.current_node)

    def _on_signal_routing_changed(self, *_):
        if self._loading_signal_controls or not self.current_node:
            return
        port_name = self.output_port_combo.currentText()
        if not port_name:
            return
        config = self.current_node.get_signal_config()
        config["input"] = {
            "type": self.VALUE_TYPE_LABELS.get(self.input_type.currentText(), "any"),
            "required": self.input_required.isChecked(),
        }
        config.setdefault("outputs", {})[port_name] = {
            "value": self.output_value.text(),
        }
        self.current_node.set_signal_config(config)

    def apply_theme(self):
        self.setStyleSheet(f"""
            NodeInspector {{
                background: {Theme.BG_COLOR.name()};
                border-left: 1px solid {Theme.INPUT_BORDER};
            }}
            QFrame {{ background: transparent; border: none; }}
            QLabel {{ color: {Theme.NODE_TEXT.name()}; background: transparent; }}
            QScrollArea, QScrollArea > QWidget > QWidget {{
                background: {Theme.BG_COLOR.name()};
                border: none;
            }}
            QComboBox, QLineEdit {{
                background: {Theme.INPUT_BG}; color: {Theme.INPUT_TEXT};
                border: 1px solid {Theme.INPUT_BORDER}; border-radius: 7px;
                padding: 7px 9px; min-height: 22px;
            }}
            QPushButton {{
                background: {Theme.NODE_BG.name()}; color: {Theme.NODE_TEXT.name()};
                border: 1px solid {Theme.INPUT_BORDER}; border-radius: 7px;
                padding: 8px;
            }}
            QPushButton:hover {{ border-color: {Theme.PORT_BG_HOVER.name()}; }}
            QCheckBox {{
                color: {Theme.NODE_TEXT_DIM.name()};
                spacing: 6px;
                padding: 2px;
            }}
            QCheckBox:checked {{ color: {Theme.NODE_TEXT.name()}; }}
        """)
        # Scope panel styles to the frames themselves.  An unscoped border on a
        # parent stylesheet is inherited by its labels and looks like a row of
        # accidental underlines.
        self.header.setStyleSheet(f"""
            QFrame#inspectorHeader {{
                background: {Theme.NODE_BG.name()};
                border: none;
            }}
        """)
        self.controls.setStyleSheet("""
            QFrame#inspectorControls {
                background: transparent;
                border: none;
            }
        """)
        self.routing_title.setStyleSheet(
            f"color: {Theme.NODE_TEXT.name()}; font-size: 12px; font-weight: 700; border: none;"
        )
        self.routing_help.setStyleSheet(
            f"color: {Theme.NODE_TEXT_DIM.name()}; font-size: 10px; border: none;"
        )
        self.eyebrow.setStyleSheet(
            f"color: {Theme.NODE_TEXT_DIM.name()}; font-size: 9px; font-weight: 700; letter-spacing: 1px; border: none;"
        )
        self.title.setStyleSheet(f"""
            QLineEdit#nodeNameEditor {{
                color: {Theme.NODE_TEXT.name()};
                background: transparent;
                font-size: 18px;
                font-weight: 750;
                border: 1px solid transparent;
                border-radius: 6px;
                padding: 2px 5px;
            }}
            QLineEdit#nodeNameEditor:hover:!read-only {{
                background: {Theme.INPUT_BG};
                border-color: {Theme.INPUT_BORDER};
            }}
            QLineEdit#nodeNameEditor:focus {{
                background: {Theme.INPUT_BG};
                border-color: {Theme.PORT_BG_HOVER.name()};
            }}
            QLineEdit#nodeNameEditor:read-only {{
                color: {Theme.NODE_TEXT_DIM.name()};
            }}
        """)
        self.category.setStyleSheet(
            f"color: {Theme.NODE_TEXT_DIM.name()}; font-size: 11px; border: none;"
        )
        self.section_label.setStyleSheet(
            f"color: {Theme.NODE_TEXT_DIM.name()}; font-size: 10px; font-weight: 700; letter-spacing: 1px; border: none;"
        )
        self.mode_hint.setStyleSheet(
            f"color: {Theme.NODE_TEXT_DIM.name()}; font-size: 10px; border: none;"
        )
        self.empty_label.setStyleSheet(
            f"color: {Theme.NODE_TEXT_DIM.name()}; padding: 30px;"
        )
        if self.current_node:
            self.refresh_node_state()
