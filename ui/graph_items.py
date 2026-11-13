from .i18n import (
    QCheckBox,
    QComboBox,
    QLabel,
    QMenu,
    QPushButton,
    QLineEdit,
    tr,
)
# ui/graph_items.py
import json
from math import hypot

from PyQt6.QtCore import (
    QObject,
    QPointF,
    QRectF,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
)
from PyQt6.QtWidgets import (
    QColorDialog,
    QFileDialog,
    QFrame,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsProxyWidget,
    QHBoxLayout,
    QInputDialog,
    QLayout,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.signals import normalise_signal_config

from .theme import Theme


CATEGORY_ICONS = {
    "动作": "⚡",
    "AI核心": "✦",
    "逻辑": "◇",
    "记忆": "◆",
    "网络与侦察": "◎",
    "通知": "●",
    "系统": "⌘",
    "文本": "T",
    "时间": "◷",
    "触发": "▶",
    "视觉": "◉",
    "General": "•",
}


class NodeSignalBridge(QObject):
    moved = pyqtSignal(str)
    ports_changed = pyqtSignal(str)


class RouteRulesEditor(QWidget):
    """Small rule-table editor used by the data router node."""

    changed = pyqtSignal()
    OPERATORS = [
        "等于",
        "不等于",
        "包含",
        "大于",
        "大于等于",
        "小于",
        "小于等于",
        "存在",
        "不存在",
    ]
    DEFAULT_RULES = [
        {"port": "True", "path": "", "operator": "等于", "target": "true"},
        {"port": "False", "path": "", "operator": "等于", "target": "false"},
    ]

    def __init__(self, defaults=None, parent=None):
        super().__init__(parent)
        self.rows = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        self.rows_layout = QVBoxLayout()
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(7)
        layout.addLayout(self.rows_layout)
        add_button = QPushButton("＋ 添加输出规则")
        add_button.clicked.connect(lambda: self.add_rule())
        layout.addWidget(add_button)
        self.set_value(defaults or self.DEFAULT_RULES, emit=False)

    def add_rule(self, rule=None, emit=True):
        rule = rule or {}
        frame = QFrame()
        frame.setObjectName("routeRuleRow")
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(7, 7, 7, 7)
        frame_layout.setSpacing(5)

        top = QHBoxLayout()
        port = QLineEdit(str(rule.get("port", f"分支{len(self.rows) + 1}")))
        port.setPlaceholderText(tr("输出端口名称"))
        path = QLineEdit(str(rule.get("path", "")))
        path.setPlaceholderText(tr("字段路径；留空判断整个 value"))
        top.addWidget(port, 2)
        top.addWidget(path, 3)

        bottom = QHBoxLayout()
        operator = QComboBox()
        operator.addItems(self.OPERATORS)
        operator.setCurrentText(str(rule.get("operator", "等于")))
        target = QLineEdit(str(rule.get("target", "true")))
        target.setPlaceholderText(tr("目标值"))
        remove = QPushButton("－")
        remove.setFixedWidth(34)
        bottom.addWidget(operator, 2)
        bottom.addWidget(target, 3)
        bottom.addWidget(remove)

        frame_layout.addLayout(top)
        frame_layout.addLayout(bottom)
        row = {
            "frame": frame,
            "port": port,
            "path": path,
            "operator": operator,
            "target": target,
        }
        self.rows.append(row)
        self.rows_layout.addWidget(frame)

        port.textChanged.connect(self.changed.emit)
        path.textChanged.connect(self.changed.emit)
        operator.currentTextChanged.connect(self.changed.emit)
        target.textChanged.connect(self.changed.emit)
        remove.clicked.connect(lambda _=False, current=row: self.remove_rule(current))
        if emit:
            self.changed.emit()

    def remove_rule(self, row):
        if row not in self.rows:
            return
        self.rows.remove(row)
        self.rows_layout.removeWidget(row["frame"])
        row["frame"].deleteLater()
        self.changed.emit()

    def get_value(self):
        return [
            {
                "port": row["port"].text().strip(),
                "path": row["path"].text().strip(),
                "operator": row["operator"].currentText(),
                "target": row["target"].text(),
            }
            for row in self.rows
            if row["port"].text().strip()
        ]

    def set_value(self, value, emit=True):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (TypeError, ValueError):
                value = []
        rules = value if isinstance(value, list) else []
        while self.rows:
            row = self.rows.pop()
            self.rows_layout.removeWidget(row["frame"])
            row["frame"].deleteLater()
        for rule in rules or self.DEFAULT_RULES:
            if isinstance(rule, dict):
                self.add_rule(rule, emit=False)
        if emit:
            self.changed.emit()


class NodeWidget(QWidget):
    config_changed = pyqtSignal()

    def __init__(self, config_schema):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 5, 10, 15)
        self.layout.setSpacing(6)

        self.inputs = {}

        for key, value_def in config_schema.items():
            if key.startswith("__"):
                continue

            label = QLabel(key)
            label.setWordWrap(True)
            # 删掉写死的 setStyleSheet
            self.layout.addWidget(label)

            if isinstance(value_def, dict) and value_def.get("$widget") == "route_rules":
                editor = RouteRulesEditor(value_def.get("default"))
                editor.changed.connect(self.config_changed.emit)
                self.layout.addWidget(editor)
                self.inputs[key] = editor

            elif isinstance(value_def, list):
                cb = QComboBox()
                cb.addItems([str(v) for v in value_def])
                cb.currentTextChanged.connect(lambda *_: self.config_changed.emit())
                self.layout.addWidget(cb)
                self.inputs[key] = cb

            elif value_def == "$FILE$":
                row = QWidget()
                hlay = QHBoxLayout(row)
                hlay.setContentsMargins(0, 0, 0, 0)
                hlay.setSpacing(4)

                le = QLineEdit()
                le.textChanged.connect(lambda *_: self.config_changed.emit())
                btn = QPushButton("...")
                btn.setFixedWidth(25)
                btn.clicked.connect(
                    lambda checked, le=le: le.setText(
                        QFileDialog.getOpenFileName(
                            None,
                            tr("选择文件"),
                            tr(""),
                            "All Files (*);;Executables (*.exe *.bat *.py)",
                        )[0]
                    )
                )

                hlay.addWidget(le)
                hlay.addWidget(btn)
                self.layout.addWidget(row)
                self.inputs[key] = le

            elif value_def == "$TEXTAREA$":
                te = QTextEdit()
                te.setAcceptRichText(False)
                te.setMinimumHeight(100)
                te.textChanged.connect(self.config_changed.emit)
                self.layout.addWidget(te)
                self.inputs[key] = te

            else:
                le = QLineEdit(str(value_def))
                le.textChanged.connect(lambda *_: self.config_changed.emit())
                self.layout.addWidget(le)
                self.inputs[key] = le

        # 核心：初始化完毕后，立刻刷一遍当前的主题皮肤
        self.apply_theme()

    def apply_theme(self):
        qss = f"""
            QLabel {{
                color: {Theme.NODE_TEXT_DIM.name()};
                font-size: 11px;
                font-weight: 600;
                border: none;
                background: transparent;
                padding-top: 5px;
            }}
            QLineEdit, QComboBox {{
                background: {Theme.INPUT_BG};
                color: {Theme.INPUT_TEXT};
                border: 1px solid {Theme.INPUT_BORDER};
                border-radius: 7px;
                padding: 7px 9px;
                min-height: 20px;
                font-size: 12px;
            }}
            QLineEdit:focus, QComboBox:focus, QTextEdit:focus {{
                border: 1px solid {Theme.PORT_BG_HOVER.name()};
            }}
            QComboBox::drop-down {{ border: none; }}
            QTextEdit {{
                background: {Theme.TEXTAREA_BG};
                color: {Theme.TEXTAREA_TEXT};
                border: 1px solid {Theme.INPUT_BORDER};
                border-radius: 7px;
                padding: 8px;
                font-size: 12px;
                font-family: Consolas;
            }}
            QPushButton {{
                background: {Theme.INPUT_BG};
                color: {Theme.INPUT_TEXT};
                border: 1px solid {Theme.INPUT_BORDER};
                border-radius: 7px;
                min-height: 30px;
            }}
            QPushButton:hover {{
                background: {Theme.NODE_TITLE_BG.name()};
                color: {Theme.NODE_TEXT.name()};
            }}
        """
        self.setStyleSheet(qss)

    def get_config(self):
        config = {}
        for k, v in self.inputs.items():
            if hasattr(v, "get_value"):
                config[k] = v.get_value()
            elif isinstance(v, QComboBox):
                config[k] = v.currentText()
            elif isinstance(v, QTextEdit):
                config[k] = v.toPlainText()
            else:
                config[k] = v.text()
        return config

    def set_config(self, config):
        """批量恢复配置，并避免每个字段都触发一次历史快照。"""
        self.blockSignals(True)
        try:
            for key, widget in self.inputs.items():
                value = config.get(key)
                if value is None:
                    continue
                widget.blockSignals(True)
                try:
                    if hasattr(widget, "set_value"):
                        widget.set_value(value, emit=False)
                    elif isinstance(widget, QComboBox):
                        widget.setCurrentText(str(value))
                    elif isinstance(widget, QTextEdit):
                        widget.setPlainText(str(value))
                    else:
                        widget.setText(str(value))
                finally:
                    widget.blockSignals(False)
        finally:
            self.blockSignals(False)
        self.config_changed.emit()

    def update_textarea(self, text):
        for v in self.inputs.values():
            if isinstance(v, QTextEdit):
                v.setPlainText(str(text))
                break


class PortItem(QGraphicsItem):
    def __init__(self, parent: QGraphicsItem, name: str, is_output: bool):
        super().__init__(parent)
        self.name = name
        self.is_output = is_output
        self.radius = 6.0
        self.is_connected = False
        self.is_drag_hovered = False
        self.setToolTip(tr(name))

    def set_drag_hover(self, state: bool):
        if self.is_drag_hovered != state:
            self.is_drag_hovered = state
            self.update()

    def set_connected(self, state: bool):
        if self.is_connected != state:
            self.is_connected = state
            self.update()

    def boundingRect(self) -> QRectF:
        return QRectF(
            -self.radius * 2, -self.radius * 2, self.radius * 4, self.radius * 4
        )

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        parent_color = getattr(self.parentItem(), "category_color", Theme.PORT_BG_HOVER)
        if self.is_drag_hovered:
            color = QColor(parent_color).lighter(135)
        elif self.is_connected:
            color = QColor(parent_color)
        else:
            color = Theme.PORT_BG_DEFAULT

        if self.is_drag_hovered:
            glow = QColor(color)
            glow.setAlpha(70)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(glow))
            painter.drawEllipse(
                QRectF(-self.radius * 1.7, -self.radius * 1.7, self.radius * 3.4, self.radius * 3.4)
            )

        painter.setBrush(QBrush(Theme.NODE_BG))
        painter.setPen(QPen(color, 2.2))
        painter.drawEllipse(
            QRectF(-self.radius, -self.radius, self.radius * 2, self.radius * 2)
        )
        inner = QColor(color)
        inner.setAlpha(220 if self.is_connected else 130)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(inner))
        painter.drawEllipse(QRectF(-2.6, -2.6, 5.2, 5.2))


class EdgeItem(QGraphicsPathItem):
    VALID_STYLES = {"curve", "orthogonal", "circuit"}

    def __init__(
        self, source_pos: QPointF, target_pos: QPointF, style: str = "curve"
    ):
        super().__init__()
        self.setZValue(-1)
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.source_pos = QPointF(source_pos)
        self.target_pos = QPointF(target_pos)
        self.source_color = QColor(Theme.EDGE_ACTIVE)
        self.target_color = QColor(Theme.PORT_BG_HOVER)
        self.edge_style = style if style in self.VALID_STYLES else "curve"
        self.update_path(source_pos, target_pos)

    def set_endpoint_colors(self, source_color, target_color=None):
        self.source_color = QColor(source_color)
        self.target_color = QColor(target_color or source_color)
        self.update()

    def set_style(self, style: str):
        style = style if style in self.VALID_STYLES else "curve"
        if self.edge_style == style:
            return
        self.edge_style = style
        self.update_path(self.source_pos, self.target_pos)

    @staticmethod
    def _orthogonal_points(p1: QPointF, p2: QPointF):
        """Route a readable Manhattan path, including backwards connections."""
        dx = p2.x() - p1.x()
        dy = p2.y() - p1.y()
        if dx >= 72.0:
            mid_x = (p1.x() + p2.x()) / 2.0
            return [
                QPointF(p1),
                QPointF(mid_x, p1.y()),
                QPointF(mid_x, p2.y()),
                QPointF(p2),
            ]

        lead = 48.0
        direction = 1.0 if dy >= 0 else -1.0
        lane_y = (
            max(p1.y(), p2.y()) + 64.0
            if direction > 0
            else min(p1.y(), p2.y()) - 64.0
        )
        return [
            QPointF(p1),
            QPointF(p1.x() + lead, p1.y()),
            QPointF(p1.x() + lead, lane_y),
            QPointF(p2.x() - lead, lane_y),
            QPointF(p2.x() - lead, p2.y()),
            QPointF(p2),
        ]

    @staticmethod
    def _circuit_points(p1: QPointF, p2: QPointF):
        """Build a PCB-like H/V/45 route without cosmetic corner nicks.

        Forward routes use one long 45-degree posture when space permits.  A
        large vertical delta uses two 45-degree shoulders and a vertical
        segment.  Backwards routes walk around the nodes using only horizontal,
        vertical and 45-degree segments, avoiding acute turns.
        """
        dx = p2.x() - p1.x()
        dy = p2.y() - p1.y()
        direction_y = 1.0 if dy >= 0.0 else -1.0

        if dx >= 36.0:
            lead = min(34.0, max(10.0, dx * 0.16))
            left_x = p1.x() + lead
            right_x = p2.x() - lead
            available = max(0.0, right_x - left_x)
            vertical_delta = abs(dy)

            if vertical_delta <= available:
                # H -> long 45° diagonal -> H.  Split spare horizontal room
                # evenly so the route stays visually balanced.
                spare = available - vertical_delta
                diagonal_start_x = left_x + spare / 2.0
                diagonal_end_x = diagonal_start_x + vertical_delta
                return [
                    QPointF(p1),
                    QPointF(diagonal_start_x, p1.y()),
                    QPointF(diagonal_end_x, p2.y()),
                    QPointF(p2),
                ]

            # Not enough horizontal distance for one diagonal to absorb the
            # entire vertical delta.  Use two 45° shoulders joined vertically.
            diagonal_run = max(4.0, available / 2.0)
            return [
                QPointF(p1),
                QPointF(left_x, p1.y()),
                QPointF(
                    left_x + diagonal_run,
                    p1.y() + direction_y * diagonal_run,
                ),
                QPointF(
                    right_x - diagonal_run,
                    p2.y() - direction_y * diagonal_run,
                ),
                QPointF(right_x, p2.y()),
                QPointF(p2),
            ]

        # Feedback/backwards links leave the source to the right, travel in a
        # clear lane above or below both nodes, then approach the target from
        # its left.  Every transition is H/V/45 and contains no acute corner.
        lead = 42.0
        diagonal_run = 22.0
        lane_y = (
            max(p1.y(), p2.y()) + 76.0
            if direction_y > 0
            else min(p1.y(), p2.y()) - 76.0
        )
        source_x = p1.x() + lead
        target_x = p2.x() - lead
        return [
            QPointF(p1),
            QPointF(source_x, p1.y()),
            QPointF(
                source_x + diagonal_run,
                p1.y() + direction_y * diagonal_run,
            ),
            QPointF(
                source_x + diagonal_run,
                lane_y - direction_y * diagonal_run,
            ),
            QPointF(source_x, lane_y),
            QPointF(target_x, lane_y),
            QPointF(
                target_x - diagonal_run,
                lane_y - direction_y * diagonal_run,
            ),
            QPointF(
                target_x - diagonal_run,
                p2.y() + direction_y * diagonal_run,
            ),
            QPointF(target_x, p2.y()),
            QPointF(p2),
        ]

    @staticmethod
    def _polyline_path(points, chamfer=0.0):
        path = QPainterPath(points[0])
        if chamfer <= 0.0 or len(points) < 3:
            for point in points[1:]:
                path.lineTo(point)
            return path

        for index in range(1, len(points) - 1):
            previous = points[index - 1]
            corner = points[index]
            following = points[index + 1]
            previous_length = hypot(
                previous.x() - corner.x(), previous.y() - corner.y()
            )
            following_length = hypot(
                following.x() - corner.x(), following.y() - corner.y()
            )
            if previous_length == 0.0 or following_length == 0.0:
                path.lineTo(corner)
                continue
            trim = min(chamfer, previous_length / 2.0, following_length / 2.0)
            before = QPointF(
                corner.x()
                + (previous.x() - corner.x()) * trim / previous_length,
                corner.y()
                + (previous.y() - corner.y()) * trim / previous_length,
            )
            after = QPointF(
                corner.x()
                + (following.x() - corner.x()) * trim / following_length,
                corner.y()
                + (following.y() - corner.y()) * trim / following_length,
            )
            path.lineTo(before)
            path.lineTo(after)
        path.lineTo(points[-1])
        return path

    def update_path(self, p1: QPointF, p2: QPointF):
        self.source_pos = QPointF(p1)
        self.target_pos = QPointF(p2)
        if self.edge_style in {"orthogonal", "circuit"}:
            points = (
                self._circuit_points(p1, p2)
                if self.edge_style == "circuit"
                else self._orthogonal_points(p1, p2)
            )
            path = self._polyline_path(points)
            self.setPath(path)
            return

        path = QPainterPath(p1)
        dx = p2.x() - p1.x()
        dy = p2.y() - p1.y()
        if dx >= 0:
            handle = max(64.0, abs(dx) * 0.46)
            ctrl1 = QPointF(p1.x() + handle, p1.y())
            ctrl2 = QPointF(p2.x() - handle, p2.y())
        else:
            bend = max(88.0, min(220.0, abs(dx) * 0.35 + abs(dy) * 0.18))
            direction = 1.0 if dy >= 0 else -1.0
            ctrl1 = QPointF(p1.x() + bend, p1.y() + direction * bend * 0.55)
            ctrl2 = QPointF(p2.x() - bend, p2.y() - direction * bend * 0.55)
        path.cubicTo(ctrl1, ctrl2, p2)
        self.setPath(path)

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(18.0)
        return stroker.createStroke(self.path())

    def boundingRect(self) -> QRectF:
        # QGraphicsPathItem only accounts for its default pen.  Our custom glow
        # is wider, so reserve a little extra paint area to avoid clipped edges.
        return super().boundingRect().adjusted(-8.0, -8.0, 8.0, 8.0)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        gradient = QLinearGradient(self.source_pos, self.target_pos)
        gradient.setColorAt(0.0, self.source_color)
        gradient.setColorAt(0.52, QColor(Theme.EDGE_ACTIVE))
        gradient.setColorAt(1.0, self.target_color)

        glow_color = QColor(self.source_color)
        glow_color.setAlpha(95 if self.isSelected() else 34)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        glow_width = {
            "curve": 5.0,
            "orthogonal": 4.5,
            "circuit": 4.0,
        }[self.edge_style]
        core_width = {
            "curve": 2.2,
            "orthogonal": 2.0,
            "circuit": 1.8,
        }[self.edge_style]
        painter.setPen(
            QPen(
                glow_color,
                8.0 if self.isSelected() else glow_width,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        )
        painter.drawPath(self.path())

        painter.setPen(
            QPen(
                QBrush(gradient),
                3.0 if self.isSelected() else core_width,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        )
        painter.drawPath(self.path())

        if self.edge_style == "circuit":
            # Two luminous vias make the H/V/45 trace read like a PCB route.
            for fraction, color in (
                (0.34, self.source_color),
                (0.68, self.target_color),
            ):
                pad = self.path().pointAtPercent(fraction)
                painter.setPen(QPen(color, 1.2))
                painter.setBrush(QBrush(QColor(Theme.NODE_BG)))
                painter.drawEllipse(pad, 3.4, 3.4)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(color))
                painter.drawEllipse(pad, 1.35, 1.35)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self.target_color))
        painter.drawEllipse(self.target_pos, 3.2, 3.2)


# ===================================================
# NodeItem
# ===================================================
class NodeHoverLabel(QGraphicsItem):
    """Screen-sized output-port badge revealed while a node is hovered."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.text = ""
        self.font = QFont("Microsoft YaHei UI", 8)
        self.font.setBold(True)
        self._rect = QRectF()
        self.setZValue(20)
        self.setFlag(
            QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True
        )
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.hide()

    def set_text(self, text):
        self.prepareGeometryChange()
        self.text = str(text)
        metrics = QFontMetricsF(self.font)
        width = metrics.horizontalAdvance(self.text) + 16.0
        height = metrics.height() + 6.0
        self._rect = QRectF(11.0, -height / 2.0, width, height)
        self.update()

    def boundingRect(self):
        return self._rect

    def paint(self, painter, option, widget=None):
        if not self.text:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        background = QColor(Theme.TOOLTIP_BG)
        background.setAlpha(232)
        accent = getattr(
            self.parentItem(), "category_color", QColor(Theme.PORT_BG_HOVER)
        )
        painter.setBrush(QBrush(background))
        painter.setPen(QPen(accent, 1.0))
        painter.drawRoundedRect(self._rect, 7.0, 7.0)
        painter.setFont(self.font)
        painter.setPen(Theme.TOOLTIP_TEXT)
        painter.drawText(self._rect, Qt.AlignmentFlag.AlignCenter, tr(self.text))


class NodeItem(QGraphicsItem):
    MODE_SIZES = {
        "icon": (76.0, 76.0),
        "standard": (190.0, 84.0),
    }

    def __init__(
        self,
        id: str,
        name: str,
        config_schema: dict = None,
        category: str = "General",
    ):
        super().__init__()
        self.id = id
        self.node_type = name
        self.name = name
        self.category = category or "General"
        self.exec_status = "Idle"
        self.is_disabled = False
        self.display_mode = "standard"
        self.is_collapsed = False  # 兼容旧工作流：icon 模式视为 collapsed
        schema = dict(config_schema) if config_schema else {}
        self.out_ports_names = schema.pop("__out_ports__", ["OUT"])
        self.out_port_descriptions = schema.pop("__out_descriptions__", {}) or {}
        self.default_input_contract = {
            "type": schema.pop("__input_type__", "any"),
            "required": bool(schema.pop("__input_required__", False)),
        }
        self.dynamic_router = bool(schema.pop("__dynamic_router__", False))
        self.signal_config = normalise_signal_config(
            {}, self.out_ports_names, self.default_input_contract
        )
        self.config_schema = schema
        self.width, self.height = self.MODE_SIZES["standard"]
        self._expanded_height = self.height

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setZValue(1)
        self.setAcceptHoverEvents(True)

        self.in_port = PortItem(self, "IN", is_output=False)
        self.out_ports = [
            PortItem(self, port_name, is_output=True)
            for port_name in self.out_ports_names
        ]

        self.widget = NodeWidget(self.config_schema) if self.config_schema else None
        self.proxy = None  # 配置已迁移到右侧检查器，不再嵌入画布节点。
        if self.widget:
            self.widget.config_changed.connect(self._on_config_changed)

        self.signals = NodeSignalBridge()
        self.port_hover_labels = {
            port.name: NodeHoverLabel(self) for port in self.out_ports
        }
        self._update_port_positions()
        self._refresh_port_hover_labels()
        self._sync_dynamic_output_ports()

    @property
    def category_icon(self):
        return CATEGORY_ICONS.get(self.category, CATEGORY_ICONS["General"])

    @property
    def category_color(self):
        return QColor(
            Theme.CATEGORY_ACCENTS.get(
                self.category, Theme.CATEGORY_ACCENTS["General"]
            )
        )

    def _on_config_changed(self):
        self._sync_dynamic_output_ports()
        self.update()

    def get_config(self):
        return self.widget.get_config() if self.widget else {}

    def set_config(self, config):
        if self.widget:
            self.widget.set_config(config or {})

    def get_signal_config(self):
        return {
            "outputs": {
                port_name: {"value": config.get("value", "")}
                for port_name, config in self.signal_config["outputs"].items()
            },
            "input": dict(self.signal_config["input"]),
        }

    def set_signal_config(self, config):
        self.signal_config = normalise_signal_config(
            config, self.out_ports_names, self.default_input_contract
        )
        self._refresh_port_hover_labels()
        self.update()

    def get_port_hover_text(self, port_name):
        output = self.signal_config["outputs"].get(port_name, {})
        parts = [tr(port_name)]
        description = self.out_port_descriptions.get(port_name, "")
        if description:
            parts.append(tr(str(description)))
        configured_value = output.get("value", "").strip()
        if configured_value:
            parts.append(f"value={configured_value}")
        return "  ·  ".join(parts)

    def _router_port_names(self):
        if not self.dynamic_router:
            return list(self.out_ports_names)
        config = self.get_config()
        rules = config.get("路由规则", [])
        names = []
        for rule in rules if isinstance(rules, list) else []:
            if not isinstance(rule, dict):
                continue
            name = str(rule.get("port", "")).strip()
            if name and name not in names:
                names.append(name)
        if config.get("未匹配时") == "走默认出口":
            fallback = str(config.get("默认出口名称", "默认")).strip() or "默认"
            if fallback not in names:
                names.append(fallback)
        return names or ["未配置"]

    def _sync_dynamic_output_ports(self):
        if not self.dynamic_router or not hasattr(self, "out_ports"):
            return
        names = self._router_port_names()
        if names == [port.name for port in self.out_ports]:
            return
        self.set_output_ports(names)

    def set_output_ports(self, names):
        """Update dynamic router pins while keeping same-named connections."""
        names = [str(name).strip() for name in names if str(name).strip()]
        names = list(dict.fromkeys(names)) or ["未配置"]
        old_ports = list(self.out_ports)
        old_by_name = {port.name: port for port in old_ports}
        reserved = {old_by_name[name] for name in names if name in old_by_name}
        used = set()
        new_ports = []

        for index, name in enumerate(names):
            port = old_by_name.get(name)
            if port in used:
                port = None
            if port is None:
                port = next(
                    (
                        candidate
                        for candidate in old_ports
                        if candidate not in used and candidate not in reserved
                    ),
                    None,
                )
            if port is None:
                port = PortItem(self, name, is_output=True)
            old_name = port.name
            port.name = name
            port.setToolTip(tr(name))
            used.add(port)
            new_ports.append(port)
            if old_name != name and old_name in self.port_hover_labels:
                label = self.port_hover_labels.pop(old_name)
                self.port_hover_labels[name] = label

        removed = [port for port in old_ports if port not in used]
        scene = self.scene()
        if scene is not None and hasattr(scene, "connections"):
            for in_port, out_port, edge in list(scene.connections):
                if out_port in removed:
                    scene.delete_edge(edge)
        for port in removed:
            label = self.port_hover_labels.pop(port.name, None)
            if label is not None:
                if label.scene() is not None:
                    label.scene().removeItem(label)
            if port.scene() is not None:
                port.scene().removeItem(port)

        for port in new_ports:
            if port.name not in self.port_hover_labels:
                self.port_hover_labels[port.name] = NodeHoverLabel(self)
        previous_outputs = self.signal_config.get("outputs", {})
        self.out_ports = new_ports
        self.out_ports_names = names
        migrated = {
            "outputs": {
                name: previous_outputs.get(name, {"value": ""}) for name in names
            },
            "input": self.signal_config.get("input", self.default_input_contract),
        }
        self.signal_config = normalise_signal_config(
            migrated, names, self.default_input_contract
        )
        self._update_port_positions()
        self._refresh_port_hover_labels()
        self.signals.moved.emit(self.id)
        self.signals.ports_changed.emit(self.id)

    def _refresh_port_hover_labels(self):
        if not hasattr(self, "port_hover_labels"):
            return
        for port in self.out_ports:
            label = self.port_hover_labels[port.name]
            label.set_text(self.get_port_hover_text(port.name))
            label.setPos(port.pos())

    def _update_port_positions(self):
        self.in_port.setPos(0, self.height / 2)
        count = max(1, len(self.out_ports))
        maximum_spacing = 22.0 if self.display_mode == "icon" else 24.0
        spacing = min(maximum_spacing, (self.height - 20) / max(1, count - 1))
        start_y = self.height / 2 - ((count - 1) * spacing) / 2
        for index, port in enumerate(self.out_ports):
            port.setPos(self.width, start_y + index * spacing)

    def set_display_mode(self, mode: str, custom_size=None):
        # compact was the original name of today's standard card.  Accept it
        # when reading older workflows, but never persist a third mode again.
        if mode == "compact":
            mode = "standard"
        if mode not in self.MODE_SIZES:
            mode = "standard"
        self.prepareGeometryChange()
        self.display_mode = mode
        self.is_collapsed = mode == "icon"
        self.width, self.height = self.MODE_SIZES[mode]
        self._expanded_height = self.height
        self._update_port_positions()
        self._refresh_port_hover_labels()
        self.update()
        if hasattr(self, "signals"):
            self.signals.moved.emit(self.id)

    def set_disabled(self, disabled: bool):
        self.is_disabled = disabled
        self.set_exec_status("Disabled" if disabled else "Idle")

    def set_exec_status(self, status: str):
        self.exec_status = status
        self.update()

    def set_display_text(self, text: str):
        if self.widget:
            self.widget.update_textarea(text)

    def boundingRect(self) -> QRectF:
        return QRectF(-7, -7, self.width + 14, self.height + 14)

    def contextMenuEvent(self, event):
        # Node naming lives in the inspector title.  Let the view provide the
        # remaining node actions instead of opening a second rename surface.
        event.ignore()

    def mouseDoubleClickEvent(self, event):
        next_mode = "standard" if self.display_mode == "icon" else "icon"
        self.set_display_mode(next_mode)
        event.accept()

    def hoverEnterEvent(self, event):
        self.setToolTip(tr(self.name))
        self._refresh_port_hover_labels()
        for label in self.port_hover_labels.values():
            label.show()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        for label in self.port_hover_labels.values():
            label.hide()
        super().hoverLeaveEvent(event)

    def itemChange(self, change, value):
        if (
            change == QGraphicsItem.GraphicsItemChange.ItemPositionChange
            and self.scene()
        ):
            new_pos = value
            scene_rect = self.scene().sceneRect()
            new_x = max(
                scene_rect.left(),
                min(new_pos.x(), scene_rect.right() - self.width),
            )
            new_y = max(
                scene_rect.top(),
                min(new_pos.y(), scene_rect.bottom() - self.height),
            )
            return QPointF(new_x, new_y)

        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            if hasattr(self, "signals"):
                self.signals.moved.emit(self.id)
        return super().itemChange(change, value)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        body = QRectF(0, 0, self.width, self.height)
        radius = 18.0 if self.display_mode == "icon" else 14.0
        body_path = QPainterPath()
        body_path.addRoundedRect(body, radius, radius)

        accent = self.category_color
        if self.is_disabled:
            accent = QColor(Theme.STATUS_SKIPPED)

        if self.isSelected():
            glow = QColor(accent)
            glow.setAlpha(75)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(glow, 7.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawPath(body_path)

        status_colors = {
            "Running": QColor(Theme.STATUS_RUNNING),
            "Success": QColor(Theme.STATUS_SUCCESS),
            "Failed": QColor(Theme.STATUS_FAILED),
            "Skipped": QColor(Theme.STATUS_SKIPPED),
            "Disabled": QColor(Theme.STATUS_SKIPPED),
        }
        border = status_colors.get(self.exec_status, accent if self.isSelected() else Theme.NODE_BORDER_DEFAULT)

        fill = QColor(Theme.NODE_BG)
        if self.is_disabled:
            fill = fill.darker(125)
        painter.setBrush(QBrush(fill))
        painter.setPen(QPen(border, 2.4 if self.isSelected() or self.exec_status != "Idle" else 1.2))
        painter.drawPath(body_path)

        icon_size = 48.0 if self.display_mode == "icon" else 52.0
        if self.display_mode == "icon":
            icon_rect = QRectF(
                (self.width - icon_size) / 2,
                (self.height - icon_size) / 2,
                icon_size,
                icon_size,
            )
        else:
            icon_rect = QRectF(14, (self.height - icon_size) / 2, icon_size, icon_size)

        icon_bg = QColor(accent)
        icon_bg.setAlpha(38)
        painter.setPen(QPen(accent, 1.2))
        painter.setBrush(QBrush(icon_bg))
        painter.drawRoundedRect(icon_rect, 13, 13)
        painter.setPen(accent)
        icon_font = painter.font()
        icon_font.setBold(True)
        icon_font.setPointSize(18 if self.display_mode == "icon" else 16)
        painter.setFont(icon_font)
        painter.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, tr(self.category_icon))

        if self.display_mode != "icon":
            text_left = icon_rect.right() + 13
            painter.setPen(Theme.DISABLED_TEXT if self.is_disabled else Theme.NODE_TEXT)
            title_font = painter.font()
            title_font.setBold(True)
            title_font.setPointSize(10)
            title_font.setStrikeOut(self.is_disabled)
            painter.setFont(title_font)
            title = QFontMetricsF(title_font).elidedText(
                tr(self.name), Qt.TextElideMode.ElideRight, int(self.width - text_left - 20)
            )
            painter.drawText(
                QRectF(text_left, 17, self.width - text_left - 20, 24),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                title,
            )

            painter.setPen(Theme.NODE_TEXT_DIM)
            meta_font = painter.font()
            meta_font.setBold(False)
            meta_font.setStrikeOut(False)
            meta_font.setPointSize(8)
            painter.setFont(meta_font)
            meta_text = self.category
            painter.drawText(
                QRectF(text_left, 43, self.width - text_left - 20, 20),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                tr(meta_text),
            )

        if self.exec_status != "Idle":
            status_color = status_colors.get(self.exec_status, accent)
            painter.setPen(QPen(fill, 2))
            painter.setBrush(QBrush(status_color))
            painter.drawEllipse(QPointF(self.width - 11, 11), 5, 5)

# ===================================================
# GroupItem
# ===================================================
class GroupItem(QGraphicsItem):
    def __init__(self, id: str, name: str, color=None):
        super().__init__()
        self.id = id
        self.name = name
        self.width = 400
        self._expanded_height = 300
        self.height = self._expanded_height
        self.is_collapsed = False
        self.is_locked = False
        self.contained_nodes = []
        self._pending_member_ids = set()
        self.group_color = QColor(color or Theme.GROUP_DEFAULT)
        if not self.group_color.isValid():
            self.group_color = QColor(Theme.GROUP_DEFAULT)

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setZValue(-2)

        self.widget = QWidget()
        self.widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.layout = QHBoxLayout(self.widget)
        self.layout.setContentsMargins(10, 0, 10, 0)
        self.layout.setSpacing(6)
        self.layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)

        self.title_label = QLabel("▼ " + self.name)
        self.title_label.setMinimumWidth(0)
        self.title_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.layout.addWidget(self.title_label, 1)

        self.toggle_cb = QCheckBox("🟢 启用")
        self.toggle_cb.setToolTip(tr("启用或禁用逻辑组中的节点"))
        self.toggle_cb.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred
        )
        self.toggle_cb.setChecked(True)
        self.toggle_cb.stateChanged.connect(self._on_toggle)
        self.layout.addWidget(self.toggle_cb)

        self.lock_cb = QCheckBox("🔓 未锁")
        self.lock_cb.setToolTip(tr("锁定后拖动逻辑组不会吸入其他节点"))
        self.lock_cb.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred
        )
        self.lock_cb.setChecked(False)
        self.lock_cb.stateChanged.connect(self._on_lock_toggle)
        self.layout.addWidget(self.lock_cb)

        self.proxy = QGraphicsProxyWidget(self)
        self.proxy.setWidget(self.widget)
        self.proxy.setPos(0, 0)
        self.sync_header_geometry()

        self.is_resizing = False
        self._drag_start_pos = None
        self.apply_theme()

    def sync_header_geometry(self):
        """Keep the embedded header clipped to the visible group width."""
        header_width = max(1, int(self.width))
        self.widget.setFixedSize(header_width, 35)
        self.proxy.resize(header_width, 35)

    def apply_theme(self):
        if hasattr(self, "title_label"):
            self.title_label.setStyleSheet(
                f"color: {Theme.NODE_TEXT.name()}; font-weight: bold; font-size: 16px; border: none;"
            )
        if hasattr(self, "toggle_cb"):
            self.toggle_cb.setStyleSheet(
                f"color: {Theme.NODE_TEXT.name()}; font-weight: bold; font-size: 12px;"
            )
        if hasattr(self, "lock_cb"):
            self.lock_cb.setStyleSheet(
                f"color: {Theme.NODE_TEXT.name()}; font-weight: bold; font-size: 12px;"
            )

    def _nodes_inside_expanded_bounds(self):
        if not self.scene():
            return []
        expanded_rect = QRectF(
            self.scenePos().x(),
            self.scenePos().y(),
            self.width,
            self._expanded_height,
        )
        return [
            item
            for item in self.scene().items(expanded_rect)
            if isinstance(item, NodeItem)
            and expanded_rect.contains(item.sceneBoundingRect())
        ]

    def set_membership_locked(self, locked, members=None):
        """锁定后，逻辑组只携带固定成员，不再按当前位置动态吸附节点。"""
        self.is_locked = bool(locked)
        if self.is_locked:
            source = members if members is not None else self._nodes_inside_expanded_bounds()
            self.contained_nodes = list(dict.fromkeys(source))
        elif not self.is_collapsed:
            self.contained_nodes = []

        self.lock_cb.blockSignals(True)
        self.lock_cb.setChecked(self.is_locked)
        self.lock_cb.setText("🔒 已锁" if self.is_locked else "🔓 未锁")
        self.lock_cb.blockSignals(False)
        self.update()

    def set_group_color(self, color):
        parsed = QColor(color)
        if parsed.isValid():
            self.group_color = parsed
            self.update()

    def get_group_color(self):
        return self.group_color.name(QColor.NameFormat.HexRgb)

    def _on_lock_toggle(self, state):
        self.set_membership_locked(state == Qt.CheckState.Checked.value)

    def _on_toggle(self, state):
        is_enabled = state == Qt.CheckState.Checked.value
        self.toggle_cb.setText("🟢 启用" if is_enabled else "🔴 禁用")
        target_items = (
            self.contained_nodes
            if self.is_collapsed or self.is_locked
            else self._nodes_inside_expanded_bounds()
        )
        for item in target_items:
            if isinstance(item, NodeItem) and item.scene() is self.scene():
                item.set_disabled(not is_enabled)
        self.update()

    def contextMenuEvent(self, event):
        menu = QMenu()
        menu.setStyleSheet(Theme.menu_stylesheet())
        rename_action = menu.addAction("✏️ 重命名逻辑组")
        lock_action = menu.addAction(
            "🔓 解锁成员" if self.is_locked else "🔒 锁定当前成员"
        )
        color_action = menu.addAction("🎨 自定义逻辑组颜色")
        res = menu.exec(event.screenPos())
        if res == rename_action:
            new_name, ok = QInputDialog.getText(
                None, tr("重命名"), tr("请输入新组名:"), text=self.name
            )
            if ok and new_name.strip():
                self.name = new_name.strip()
                arrow = "▶ " if self.is_collapsed else "▼ "
                self.title_label.setText(arrow + self.name)
        elif res == lock_action:
            self.set_membership_locked(not self.is_locked)
        elif res == color_action:
            color = QColorDialog.getColor(
                self.group_color, None, "选择逻辑组颜色"
            )
            if color.isValid():
                self.set_group_color(color)
        event.accept()

    def mouseDoubleClickEvent(self, event):
        title_rect = QRectF(0, 0, self.width, 35)
        if title_rect.contains(event.pos()):
            self.prepareGeometryChange()
            self.is_collapsed = not self.is_collapsed

            if self.is_collapsed:
                if not self.is_locked:
                    self.contained_nodes = self._nodes_inside_expanded_bounds()
                for item in self.contained_nodes:
                    if item.scene() is self.scene():
                        item.hide()
                self._expanded_height = self.height
                self.height = 35
                self.title_label.setText("▶ " + self.name)
            else:
                self.height = self._expanded_height
                for item in self.contained_nodes:
                    if item.scene() is self.scene():
                        item.show()
                if not self.is_locked:
                    self.contained_nodes = []
                self.title_label.setText("▼ " + self.name)

            self.update()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self.width, self.height)

    def mousePressEvent(self, event):
        if not self.is_collapsed:
            resize_rect = QRectF(self.width - 20, self.height - 20, 20, 20)
            if resize_rect.contains(event.pos()):
                self.is_resizing = True
                event.accept()
                return
        self._drag_start_pos = self.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.is_resizing and not self.is_collapsed:
            self.prepareGeometryChange()
            self.width = max(250, event.pos().x())
            self.height = max(100, event.pos().y())
            self._expanded_height = self.height
            self.sync_header_geometry()
            self.update()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.is_resizing:
            self.is_resizing = False
            self._drag_start_pos = None
            event.accept()
        else:
            super().mouseReleaseEvent(event)
            self._drag_start_pos = None

    def itemChange(self, change, value):
        if (
            change == QGraphicsItem.GraphicsItemChange.ItemPositionChange
            and self.scene()
            and self._drag_start_pos
        ):
            delta = value - self.pos()
            target_items = (
                self.contained_nodes
                if self.is_collapsed or self.is_locked
                else self._nodes_inside_expanded_bounds()
            )
            for item in target_items:
                if isinstance(item, NodeItem) and item.scene() is self.scene():
                    item.setPos(item.pos() + delta)
                    item.signals.moved.emit(item.id)
        return super().itemChange(change, value)

    def paint(self, painter: QPainter, option, widget=None):
        path = QPainterPath()
        path.addRoundedRect(self.boundingRect(), 10, 10)

        bg_color = QColor(self.group_color)
        bg_color.setAlpha(42 if self.toggle_cb.isChecked() else 24)
        painter.setBrush(QBrush(bg_color))

        pen_color = (
            QColor(Theme.STATUS_SKIPPED)
            if not self.toggle_cb.isChecked()
            else QColor(self.group_color)
        )
        painter.setPen(QPen(pen_color, 2 if self.isSelected() else 1))
        painter.drawPath(path)

        if not self.is_collapsed:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(Theme.NODE_TEXT_DIM))
            triangle = [
                QPointF(self.width - 15, self.height - 3),
                QPointF(self.width - 3, self.height - 15),
                QPointF(self.width - 3, self.height - 3),
            ]
            painter.drawPolygon(triangle)
