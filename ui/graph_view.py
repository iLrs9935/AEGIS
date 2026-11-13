from .i18n import QAction, QMenu, tr
# ui/graph_view.py
import json
import os
import sys
import uuid

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import (
    QColor,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QTransform,
)
from PyQt6.QtWidgets import (
    QColorDialog,
    QFileDialog,
    QFrame,
    QGraphicsProxyWidget,
    QGraphicsScene,
    QGraphicsView,
    QInputDialog,
)

from core.event_bus import bus
from nodes import NODE_REGISTRY

from .graph_items import EdgeItem, GroupItem, NodeItem, PortItem
from .theme import Theme


class AEGISScene(QGraphicsScene):
    def __init__(self, edge_style="curve"):
        super().__init__()
        self.setBackgroundBrush(Theme.SCENE_BG)
        self.setSceneRect(-50000, -50000, 100000, 100000)

        self.draft_edge = None
        self.start_port = None
        self.hovered_port = None
        self.connections = []
        self.edge_style = edge_style

        # ================= 背景图记忆模块 =================
        self.bg_pixmap = None
        self.bg_opacity = 0.15
        self.bg_image_path = None  # 新增：用于记录文件绝对路径

        # 启动时自动读取硬盘里的记忆
        self._load_bg_config()

    def _get_config_path(self):
        """精准定位到 data 目录下的 ui_config.json"""
        if getattr(sys, "frozen", False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        data_dir = os.path.join(base_dir, "data")
        os.makedirs(data_dir, exist_ok=True)  # 确保 data 目录一定存在
        return os.path.join(data_dir, "ui_config.json")

    def _load_bg_config(self):
        """唤醒记忆：读取并加载背景"""
        config_path = self._get_config_path()
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    self.bg_image_path = config.get("bg_image_path")
                    self.bg_opacity = config.get("bg_opacity", 0.15)

                    if self.bg_image_path and os.path.exists(self.bg_image_path):
                        self.bg_pixmap = QPixmap(self.bg_image_path)
            except Exception as e:
                bus.log_emitted.emit("WARN", "System", f"⚠️ 读取 UI 配置失败: {e}")

    def save_bg_config(self):
        """写入记忆：将当前设置保存到硬盘"""
        config_path = self._get_config_path()
        config = {}
        # 如果文件已存在，先读出来（为了以后咱们存主题皮肤的时候不覆盖掉其它数据）
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception:
                pass

        # 覆写背景配置
        config["bg_image_path"] = self.bg_image_path
        config["bg_opacity"] = self.bg_opacity

        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            bus.log_emitted.emit("ERROR", "System", f"💾 保存 UI 配置失败: {e}")

    def drawBackground(self, painter: QPainter, rect: QRectF):
        """绘制 n8n 风格的低干扰点阵画布。"""
        grid_size = Theme.GRID_SIZE
        left = int(rect.left()) - (int(rect.left()) % grid_size)
        top = int(rect.top()) - (int(rect.top()) % grid_size)

        minor = QColor(Theme.GRID_COLOR)
        minor.setAlpha(150)
        major = QColor(Theme.GRID_COLOR).lighter(135)
        major.setAlpha(190)
        x = left
        while x < rect.right():
            y = top
            while y < rect.bottom():
                is_major = (
                    round(x / grid_size) % 4 == 0
                    and round(y / grid_size) % 4 == 0
                )
                painter.setPen(QPen(major if is_major else minor, 2.0 if is_major else 1.2))
                painter.drawPoint(int(x), int(y))
                y += grid_size
            x += grid_size

    def mousePressEvent(self, event):
        item = self.itemAt(event.scenePos(), QTransform())
        if isinstance(item, PortItem):
            # 如果按住引脚往外拖，不再粗暴地断开原有的线，而是永远拉出一条新线
            self.start_port = item
            self.draft_edge = EdgeItem(
                item.scenePos(), event.scenePos(), style=self.edge_style
            )
            parent_color = getattr(item.parentItem(), "category_color", Theme.EDGE_ACTIVE)
            self.draft_edge.set_endpoint_colors(parent_color, Theme.PORT_BG_HOVER)
            self.addItem(self.draft_edge)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.draft_edge and self.start_port:
            self.draft_edge.update_path(self.start_port.scenePos(), event.scenePos())
            item = self.itemAt(event.scenePos(), QTransform())
            if (
                isinstance(item, PortItem)
                and item != self.start_port
                and item.is_output != self.start_port.is_output
            ):
                if self.hovered_port != item:
                    if self.hovered_port:
                        self.hovered_port.set_drag_hover(False)
                    self.hovered_port = item
                    self.hovered_port.set_drag_hover(True)
            else:
                if self.hovered_port:
                    self.hovered_port.set_drag_hover(False)
                    self.hovered_port = None
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.draft_edge:
            if self.hovered_port:
                self.hovered_port.set_drag_hover(False)
                self.hovered_port = None

            item = self.itemAt(event.scenePos(), QTransform())
            if (
                isinstance(item, PortItem)
                and item != self.start_port
                and item.is_output != self.start_port.is_output
            ):
                in_port = item if not item.is_output else self.start_port
                out_port = item if item.is_output else self.start_port

                # 【核心改造 2】：不再 pop 删除旧线，直接追加新线！
                self.connections.append((in_port, out_port, self.draft_edge))

                in_port.set_connected(True)
                out_port.set_connected(True)

                self.draft_edge.set_endpoint_colors(
                    getattr(out_port.parentItem(), "category_color", Theme.EDGE_ACTIVE),
                    getattr(in_port.parentItem(), "category_color", Theme.PORT_BG_HOVER),
                )

                self.draft_edge.update_path(out_port.scenePos(), in_port.scenePos())
                self.draft_edge.setPen(
                    QPen(
                        Theme.EDGE_ACTIVE,
                        2.0,
                        Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap,
                    )
                )
            else:
                self.removeItem(self.draft_edge)

            self.draft_edge = None
            self.start_port = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def delete_edge(self, edge: EdgeItem):
        """外科手术：只切断一根线，并动态恢复引脚状态"""
        conn_to_remove = None
        # 在多线列表中找到对应的记录
        for conn in self.connections:
            if conn[2] == edge:
                conn_to_remove = conn
                break

        if conn_to_remove:
            in_port, out_port, _ = conn_to_remove
            self.connections.remove(conn_to_remove)
            self.removeItem(edge)

            # 【完美细节】：检查这两个引脚上是不是还有其他的线？
            # 如果没有别的线了，引脚才恢复成暗灰色；如果还有线，继续保持亮色。
            in_connected = any(c[0] == in_port for c in self.connections)
            out_connected = any(c[1] == out_port for c in self.connections)

            in_port.set_connected(in_connected)
            out_port.set_connected(out_connected)

    def update_connections(self, node_id: str):
        for in_port, out_port, edge_item in self.connections:
            if (
                in_port.parentItem().id == node_id
                or out_port.parentItem().id == node_id
            ):
                edge_item.update_path(out_port.scenePos(), in_port.scenePos())

    def delete_node(self, node):
        ports_to_check = [node.in_port] + getattr(node, "out_ports", [])
        edges_to_remove = []

        for conn in self.connections:
            in_port, out_port, edge = conn
            if in_port in ports_to_check or out_port in ports_to_check:
                self.removeItem(edge)
                edges_to_remove.append(conn)

        # 清理列表
        for conn in edges_to_remove:
            self.connections.remove(conn)

        # 重新计算剩余引脚的连接状态
        for port in ports_to_check:
            port.set_connected(False)

        # 刷新全场引脚状态（安全兜底）
        for in_port, out_port, _ in self.connections:
            in_port.set_connected(True)
            out_port.set_connected(True)

        for item in self.items():
            if isinstance(item, GroupItem) and node in item.contained_nodes:
                item.contained_nodes.remove(node)

        self.removeItem(node)

    def delete_group(self, group):
        """删除逻辑组但保留成员节点；折叠组中的节点必须先恢复可见。"""
        for node in list(getattr(group, "contained_nodes", [])):
            if isinstance(node, NodeItem) and node.scene() is self:
                node.show()
        group.contained_nodes = []
        self.removeItem(group)


# ui/graph_view.py


class AEGISView(QGraphicsView):
    def __init__(self, scene: AEGISScene):
        super().__init__(scene)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        # 设置 FullViewportUpdate 保证缩放平移时不留残影
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)

        # 左键空白区域拖动用于框选；中键平移仍由下方鼠标事件单独接管。
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        # 必须完整框住图元才选中，避免框内节点时把背后的大逻辑组误选上。
        self.setRubberBandSelectionMode(Qt.ItemSelectionMode.ContainsItemShape)

        # [核心新增] 解锁视角锚点：允许以鼠标为中心无限缩放和平移
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

        # [核心新增] 取消对齐限制：这是防止“撞墙”的关键，允许画布滚动到无限远
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        # 隐藏滚动条以获得纯净的黑板感
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

        bus.node_text_updated.connect(self._on_node_text_updated)

        # 初始化缩放比例
        self._zoom = 1.0
        self._is_panning = False
        self._pan_start = None
        self._clipboard = None
        self._paste_count = 0

        # 画布历史使用完整快照，避免每种节点操作都维护一套易漏的反向命令。
        self._history = []
        self._history_index = -1
        self._history_limit = 100
        self._history_restoring = False
        self._history_timer = QTimer(self)
        self._history_timer.setSingleShot(True)
        self._history_timer.setInterval(250)
        self._history_timer.timeout.connect(self._capture_history_now)
        self.scene().changed.connect(self._schedule_history_capture)
        self.reset_history()

    # =========================================================
    # 画布快照与撤销/重做
    # =========================================================
    @staticmethod
    def _serialize_node(node):
        return {
            "id": node.id,
            "type": getattr(node, "node_type", node.name),
            "name": node.name,
            "category": getattr(node, "category", "General"),
            "display_mode": getattr(node, "display_mode", "standard"),
            "x": node.pos().x(),
            "y": node.pos().y(),
            "w": node.width,
            "h": node.height,
            "_expanded_height": node._expanded_height,
            "config": node.get_config(),
            "signal_config": node.get_signal_config(),
            "is_disabled": node.is_disabled,
            "is_collapsed": getattr(node, "is_collapsed", False),
        }

    @staticmethod
    def _serialize_group(group):
        return {
            "id": group.id,
            "name": group.name,
            "x": group.pos().x(),
            "y": group.pos().y(),
            "w": group.width,
            "h": group._expanded_height,
            "is_disabled": not group.toggle_cb.isChecked(),
            "is_collapsed": getattr(group, "is_collapsed", False),
            "is_locked": getattr(group, "is_locked", False),
            "color": group.get_group_color(),
            "member_ids": [
                node.id
                for node in getattr(group, "contained_nodes", [])
                if isinstance(node, NodeItem) and node.scene() is group.scene()
            ],
        }

    def _serialize_scene(self):
        scene = self.scene()
        nodes = sorted(
            (
                self._serialize_node(item)
                for item in scene.items()
                if isinstance(item, NodeItem)
            ),
            key=lambda item: item["id"],
        )
        groups = sorted(
            (
                self._serialize_group(item)
                for item in scene.items()
                if isinstance(item, GroupItem)
            ),
            key=lambda item: item["id"],
        )
        edges = sorted(
            (
                {
                    "src_id": out_port.parentItem().id,
                    "src_port": out_port.name,
                    "tgt_id": in_port.parentItem().id,
                    "tgt_port": in_port.name,
                }
                for in_port, out_port, _ in scene.connections
            ),
            key=lambda item: (
                item["src_id"],
                item["src_port"],
                item["tgt_id"],
                item["tgt_port"],
            ),
        )
        return {"nodes": nodes, "groups": groups, "edges": edges}

    def _create_group_from_data(self, data, position_offset=None, new_id=None):
        group = GroupItem(
            new_id or data["id"],
            data["name"],
            color=data.get("color", Theme.GROUP_DEFAULT.name()),
        )
        offset_x, offset_y = position_offset or (0.0, 0.0)
        group.setPos(data.get("x", 0.0) + offset_x, data.get("y", 0.0) + offset_y)
        group.width = data.get("w", 400)
        group._expanded_height = data.get("h", 300)
        group.height = group._expanded_height
        if group.proxy:
            group.sync_header_geometry()
        self.scene().addItem(group)
        if data.get("is_disabled"):
            group.toggle_cb.setChecked(False)
        group.is_locked = bool(data.get("is_locked", False))
        group._pending_member_ids = set(data.get("member_ids", []))
        if data.get("is_collapsed"):
            group.is_collapsed = True
            group.title_label.setText("▶ " + group.name)
        return group

    def _finalize_group_state(self, group, node_map=None):
        """节点创建后恢复固定成员与折叠状态。"""
        pending_ids = getattr(group, "_pending_member_ids", set())
        members = []
        if pending_ids and node_map:
            members = [node_map[node_id] for node_id in pending_ids if node_id in node_map]
        elif group.is_locked or group.is_collapsed:
            members = group._nodes_inside_expanded_bounds()

        if group.is_locked:
            group.set_membership_locked(True, members=members)
        else:
            group.set_membership_locked(False)
            if group.is_collapsed:
                group.contained_nodes = members
        group._pending_member_ids = set()

        if not group.is_collapsed:
            return

        expanded_rect = QRectF(
            group.pos().x(),
            group.pos().y(),
            group.width,
            group._expanded_height,
        )
        if not group.contained_nodes:
            group.contained_nodes = [
                item
                for item in self.scene().items(expanded_rect)
                if isinstance(item, NodeItem)
                and expanded_rect.contains(item.sceneBoundingRect())
            ]
        for node in group.contained_nodes:
            node.hide()
        group.prepareGeometryChange()
        group.height = 35
        group.title_label.setText("▶ " + group.name)

    def _create_node_from_data(self, data, position_offset=None, new_id=None):
        node_type = data.get("type", data["name"])
        meta = NODE_REGISTRY.get(node_type)
        if not meta:
            bus.log_emitted.emit(
                "WARN", "UI", f"无法恢复未注册节点: {node_type}"
            )
            return None

        node = NodeItem(
            new_id or data["id"],
            node_type,
            meta["schema"],
            category=data.get("category", meta.get("category", "General")),
        )
        node.name = data.get("name", node_type)
        offset_x, offset_y = position_offset or (0.0, 0.0)
        node.setPos(data.get("x", 0.0) + offset_x, data.get("y", 0.0) + offset_y)
        display_mode = data.get(
            "display_mode", "icon" if data.get("is_collapsed") else "standard"
        )
        # Both legacy compact cards and the old resizable standard cards now
        # migrate to the single fixed-size standard presentation.
        node.set_display_mode("icon" if display_mode == "icon" else "standard")
        node.set_config(data.get("config", {}))
        node.set_signal_config(data.get("signal_config", {}))

        if data.get("is_disabled"):
            node.set_disabled(True)

        node.signals.moved.connect(self.scene().update_connections)
        self.scene().addItem(node)
        return node

    def _create_edge_from_data(self, data, node_map):
        src_node = node_map.get(data["src_id"])
        tgt_node = node_map.get(data["tgt_id"])
        if not src_node or not tgt_node:
            return None

        src_port = next(
            (port for port in src_node.out_ports if port.name == data["src_port"]),
            None,
        )
        tgt_port = tgt_node.in_port
        if not src_port or not tgt_port:
            return None

        edge = EdgeItem(
            src_port.scenePos(),
            tgt_port.scenePos(),
            style=getattr(self.scene(), "edge_style", "curve"),
        )
        edge.set_endpoint_colors(src_node.category_color, tgt_node.category_color)
        self.scene().addItem(edge)
        self.scene().connections.append((tgt_port, src_port, edge))
        src_port.set_connected(True)
        tgt_port.set_connected(True)
        edge.update_path(src_port.scenePos(), tgt_port.scenePos())
        return edge

    def _restore_scene(self, data):
        self._history_restoring = True
        self._history_timer.stop()
        try:
            scene = self.scene()
            scene.clear()
            scene.connections = []
            node_map = {}
            groups = []

            for group_data in data.get("groups", []):
                groups.append(self._create_group_from_data(group_data))
            for node_data in data.get("nodes", []):
                node = self._create_node_from_data(node_data)
                if node:
                    node_map[node_data["id"]] = node
            for group in groups:
                self._finalize_group_state(group, node_map)
            for edge_data in data.get("edges", []):
                self._create_edge_from_data(edge_data, node_map)

            scene.clearSelection()
            scene.update()
        finally:
            self._history_restoring = False

    def _schedule_history_capture(self, *_):
        if not self._history_restoring:
            self._history_timer.start()

    def _capture_history_now(self):
        if self._history_restoring:
            return

        serialized = json.dumps(
            self._serialize_scene(), ensure_ascii=False, sort_keys=True
        )
        if (
            self._history_index >= 0
            and self._history[self._history_index] == serialized
        ):
            return

        if self._history_index < len(self._history) - 1:
            self._history = self._history[: self._history_index + 1]
        self._history.append(serialized)
        if len(self._history) > self._history_limit:
            self._history.pop(0)
        self._history_index = len(self._history) - 1

    def reset_history(self):
        """把当前画布设为新的撤销起点（新建/加载工作流时调用）。"""
        self._history_timer.stop()
        self._history = []
        self._history_index = -1
        self._capture_history_now()

    def undo(self):
        self._history_timer.stop()
        self._capture_history_now()
        if self._history_index <= 0:
            bus.log_emitted.emit("INFO", "UI", "没有可撤销的操作")
            return False

        self._history_index -= 1
        self._restore_scene(json.loads(self._history[self._history_index]))
        bus.log_emitted.emit("INFO", "UI", "↶ 已撤销")
        return True

    def redo(self):
        self._history_timer.stop()
        self._capture_history_now()
        if self._history_index >= len(self._history) - 1:
            bus.log_emitted.emit("INFO", "UI", "没有可重做的操作")
            return False

        self._history_index += 1
        self._restore_scene(json.loads(self._history[self._history_index]))
        bus.log_emitted.emit("INFO", "UI", "↷ 已重做")
        return True

    def _on_node_text_updated(self, node_id, text):
        """收到信号后，遍历场景找到对应的节点并更新文字"""
        for item in self.scene().items():
            if isinstance(item, NodeItem) and item.id == node_id:
                item.set_display_text(text)
                break

    def show_context_menu(self, pos):
        """接管全局右键：实现精准打击 (新增连线识别)"""
        scene_pos = self.mapToScene(pos)
        item = self.scene().itemAt(scene_pos, QTransform())

        # 1. 向上追溯，精准识别点中了什么
        target_item = item
        while target_item is not None:
            if isinstance(target_item, NodeItem):
                self._show_item_menu(target_item, "节点", pos)
                return
            if isinstance(target_item, GroupItem):
                self._show_item_menu(target_item, "逻辑组", pos)
                return
            if isinstance(target_item, EdgeItem):
                self._show_item_menu(target_item, "连线", pos)  # <--- [新增] 识别连线
                return
            target_item = target_item.parentItem()

        # 2. 点在空白处，弹出【添加菜单】
        menu = QMenu(self)
        menu.setStyleSheet(Theme.menu_stylesheet())

        add_group_action = QAction("📦 添加逻辑编组", self)
        add_group_action.triggered.connect(lambda: self._add_group_to_scene(pos))
        menu.addAction(add_group_action)

        selected_node_count = sum(
            isinstance(item, NodeItem) for item in self.scene().selectedItems()
        )
        if selected_node_count:
            group_selection_action = QAction(
                f"🔒 将选中的 {selected_node_count} 个节点建立为锁定组", self
            )
            group_selection_action.triggered.connect(self.create_group_from_selection)
            menu.addAction(group_selection_action)
        menu.addSeparator()

        if not NODE_REGISTRY:
            error_action = QAction("❌ 节点注册表为空 (加载失败)", self)
            error_action.setEnabled(False)
            menu.addAction(error_action)

        categories = {}
        for name, meta in NODE_REGISTRY.items():
            cat = meta["category"]
            if cat not in categories:
                categories[cat] = menu.addMenu(cat)

            action = QAction(name, self)
            action.triggered.connect(
                lambda checked, n=name, p=pos: self._add_node_to_scene(n, p)
            )
            categories[cat].addAction(action)

        menu.exec(self.mapToGlobal(pos))

    def _load_background_image(self):
        """弹出文件选择框加载背景"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, tr("选择背景图片"), tr(""), "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if file_path:
            self.scene().bg_pixmap = QPixmap(file_path)
            self.scene().bg_image_path = file_path  # 1. 更新路径
            self.scene().save_bg_config()  # 2. 触发硬盘存档！
            self.scene().update()

    def _adjust_background_opacity(self):
        """弹出滑动块调整透明度"""
        current_opacity = int(self.scene().bg_opacity * 100)
        val, ok = QInputDialog.getInt(
            self, tr("背景透明度"), tr("请输入透明度百分比 (1 - 100):"), current_opacity, 1, 100
        )
        if ok:
            self.scene().bg_opacity = val / 100.0
            self.scene().save_bg_config()  # 👉 触发硬盘存档！
            self.scene().update()

    def _clear_background_image(self):
        """一键清空背景"""
        self.scene().bg_pixmap = None
        self.scene().bg_image_path = None  # 1. 抹除路径
        self.scene().save_bg_config()  # 2. 触发硬盘存档！
        self.scene().update()
        bus.log_emitted.emit("INFO", "UI", "🗑️ 背景已清空")

    def _show_item_menu(self, item, item_type, pos):
        """专门为节点、组、连线弹出的操作菜单"""
        if isinstance(item, NodeItem) and not item.isSelected():
            self.scene().clearSelection()
            item.setSelected(True)

        menu = QMenu(self)
        menu.setStyleSheet(Theme.menu_stylesheet())

        # 节点名在右侧配置标题中直接编辑；这里只保留逻辑组重命名。
        rename_action = None
        if isinstance(item, GroupItem):
            rename_action = menu.addAction(f"✏️ 重命名{item_type}")

        icon_mode_action = standard_mode_action = None
        if isinstance(item, NodeItem):
            size_menu = menu.addMenu("▣ 节点显示")
            icon_mode_action = size_menu.addAction("纯图标")
            standard_mode_action = size_menu.addAction("标准卡片")

        group_selection_action = None
        if item_type == "节点":
            selected_node_count = sum(
                isinstance(selected, NodeItem)
                for selected in self.scene().selectedItems()
            )
            if selected_node_count:
                group_selection_action = menu.addAction(
                    f"🔒 将选中的 {selected_node_count} 个节点建立为锁定组"
                )

        lock_action = None
        group_color_action = None
        if isinstance(item, GroupItem):
            lock_action = menu.addAction(
                "🔓 解锁逻辑组成员"
                if item.is_locked
                else "🔒 锁定逻辑组当前成员"
            )
            group_color_action = menu.addAction("🎨 自定义逻辑组颜色")

        delete_action = menu.addAction(f"🗑️ 删除{item_type}")

        res = menu.exec(self.mapToGlobal(pos))

        if rename_action and res == rename_action:
            new_name, ok = QInputDialog.getText(
                self, tr("重命名"), tr(f"请输入新{item_type}名称:"), text=item.name
            )
            if ok and new_name.strip():
                item.name = new_name.strip()
                if hasattr(item, "title_label"):
                    arrow = "▶ " if item.is_collapsed else "▼ "
                    item.title_label.setText(arrow + item.name)
                item.update()

        elif icon_mode_action and res == icon_mode_action:
            item.set_display_mode("icon")

        elif standard_mode_action and res == standard_mode_action:
            item.set_display_mode("standard")

        elif group_selection_action and res == group_selection_action:
            self.create_group_from_selection()

        elif lock_action and res == lock_action:
            item.set_membership_locked(not item.is_locked)
            self._history_timer.stop()
            self._capture_history_now()

        elif group_color_action and res == group_color_action:
            color = QColorDialog.getColor(
                item.group_color, self, "选择逻辑组颜色"
            )
            if color.isValid():
                item.set_group_color(color)
                self._history_timer.stop()
                self._capture_history_now()

        elif res == delete_action:
            if isinstance(item, NodeItem):
                self.scene().delete_node(item)
            elif isinstance(item, EdgeItem):
                # [新增]：调用刚刚写的精准切脉函数
                self.scene().delete_edge(item)
            elif isinstance(item, GroupItem):
                self.scene().delete_group(item)
            else:
                self.scene().removeItem(item)

    def _add_group_to_scene(self, view_pos):
        """实例化一个逻辑编组框"""
        scene_pos = self.mapToScene(view_pos)
        from .graph_items import GroupItem

        group = GroupItem(str(uuid.uuid4()), "未命名逻辑组")
        group.setPos(scene_pos)
        self.scene().addItem(group)
        self._history_timer.stop()
        self._capture_history_now()

    def create_group_from_selection(self):
        """用框选/多选节点的外接矩形建立一个成员已锁定的逻辑组。"""
        selected_nodes = [
            item for item in self.scene().selectedItems() if isinstance(item, NodeItem)
        ]
        if not selected_nodes:
            bus.log_emitted.emit("INFO", "UI", "请先框选需要编组的节点")
            return False

        bounds = selected_nodes[0].sceneBoundingRect()
        for node in selected_nodes[1:]:
            bounds = bounds.united(node.sceneBoundingRect())

        margin_x = 30.0
        margin_top = 50.0
        margin_bottom = 30.0
        group = GroupItem(str(uuid.uuid4()), "未命名逻辑组")
        group.setPos(bounds.left() - margin_x, bounds.top() - margin_top)
        group.width = max(250.0, bounds.width() + margin_x * 2)
        group._expanded_height = max(
            100.0, bounds.height() + margin_top + margin_bottom
        )
        group.height = group._expanded_height
        group.sync_header_geometry()
        self.scene().addItem(group)
        group.set_membership_locked(True, members=selected_nodes)

        self.scene().clearSelection()
        group.setSelected(True)
        self._history_timer.stop()
        self._capture_history_now()
        bus.log_emitted.emit(
            "SUCCESS",
            "UI",
            f"🔒 已将 {len(selected_nodes)} 个节点建立为锁定逻辑组",
        )
        return True

    def _add_node_to_scene(self, node_name: str, view_pos):
        scene_pos = self.mapToScene(view_pos)
        meta = NODE_REGISTRY[node_name]
        node = NodeItem(
            str(uuid.uuid4()),
            node_name,
            config_schema=meta.get("schema", {}),
            category=meta.get("category", "General"),
        )
        node.setPos(scene_pos)
        node.signals.moved.connect(self.scene().update_connections)
        self.scene().addItem(node)

    def copy_selection(self):
        """复制选中的节点/逻辑组，以及选中节点之间的内部连线。"""
        selected_items = self.scene().selectedItems()
        selected_nodes = {
            item.id: item for item in selected_items if isinstance(item, NodeItem)
        }
        selected_groups = {
            item.id: item for item in selected_items if isinstance(item, GroupItem)
        }

        # 选中逻辑组时，把完整位于组内的节点一并复制。
        for group in selected_groups.values():
            group_rect = group.sceneBoundingRect()
            candidates = (
                group.contained_nodes
                if group.is_collapsed or group.is_locked
                else self.scene().items(group_rect)
            )
            for item in candidates:
                if (
                    isinstance(item, NodeItem)
                    and (
                        group.is_collapsed
                        or group.is_locked
                        or group_rect.contains(item.sceneBoundingRect())
                    )
                ):
                    selected_nodes[item.id] = item

        if not selected_nodes and not selected_groups:
            bus.log_emitted.emit("INFO", "UI", "没有可复制的节点或逻辑组")
            return False

        positions = [item.pos() for item in selected_nodes.values()]
        positions.extend(item.pos() for item in selected_groups.values())
        anchor_x = min(position.x() for position in positions)
        anchor_y = min(position.y() for position in positions)

        nodes = []
        for node in selected_nodes.values():
            data = self._serialize_node(node)
            data["x"] -= anchor_x
            data["y"] -= anchor_y
            nodes.append(data)

        groups = []
        for group in selected_groups.values():
            data = self._serialize_group(group)
            data["x"] -= anchor_x
            data["y"] -= anchor_y
            groups.append(data)

        selected_node_ids = set(selected_nodes)
        edges = []
        for in_port, out_port, _ in self.scene().connections:
            src_id = out_port.parentItem().id
            tgt_id = in_port.parentItem().id
            if src_id in selected_node_ids and tgt_id in selected_node_ids:
                edges.append(
                    {
                        "src_id": src_id,
                        "src_port": out_port.name,
                        "tgt_id": tgt_id,
                        "tgt_port": in_port.name,
                    }
                )

        self._clipboard = {"nodes": nodes, "groups": groups, "edges": edges}
        self._paste_count = 0
        bus.log_emitted.emit(
            "INFO",
            "UI",
            f"📋 已复制 {len(nodes)} 个节点、{len(groups)} 个逻辑组和 {len(edges)} 条连线",
        )
        return True

    def paste_clipboard(self):
        """把内部画布剪贴板粘贴到鼠标位置，并为所有图元生成新 ID。"""
        if not self._clipboard:
            bus.log_emitted.emit("INFO", "UI", "画布剪贴板为空")
            return False

        from PyQt6.QtGui import QCursor

        view_mouse_pos = self.mapFromGlobal(QCursor.pos())
        if not self.viewport().rect().contains(view_mouse_pos):
            view_mouse_pos = self.viewport().rect().center()
        scene_mouse_pos = self.mapToScene(view_mouse_pos)
        cascade_offset = self._paste_count * 20.0
        position_offset = (
            scene_mouse_pos.x() + cascade_offset,
            scene_mouse_pos.y() + cascade_offset,
        )

        self.scene().clearSelection()
        node_map = {}
        pasted_groups = []

        for group_data in self._clipboard.get("groups", []):
            group = self._create_group_from_data(
                group_data,
                position_offset=position_offset,
                new_id=str(uuid.uuid4()),
            )
            pasted_groups.append(group)
            group.setSelected(True)

        for node_data in self._clipboard.get("nodes", []):
            new_id = str(uuid.uuid4())
            node = self._create_node_from_data(
                node_data,
                position_offset=position_offset,
                new_id=new_id,
            )
            if node:
                node_map[node_data["id"]] = node
                node.setSelected(True)

        for group in pasted_groups:
            self._finalize_group_state(group, node_map)

        for edge_data in self._clipboard.get("edges", []):
            self._create_edge_from_data(edge_data, node_map)

        self._paste_count += 1
        self._history_timer.stop()
        self._capture_history_now()
        bus.log_emitted.emit(
            "SUCCESS",
            "UI",
            f"📦 已粘贴 {len(node_map)} 个节点和 {len(self._clipboard.get('edges', []))} 条连线",
        )
        return True

    def keyPressEvent(self, event):
        """画布级快捷键拦截中心"""

        # ==========================================
        # 0. 🚨 终极焦点保护层 (场景级焦点判定)
        # ==========================================

        # 【核心黑魔法】：询问当前画布场景，谁拿到了“内部焦点”？
        # 如果你点击了节点内部的输入框、文本域或下拉框，
        # 这个 focus_item 就会变成包装它们的 QGraphicsProxyWidget！
        focus_item = self.scene().focusItem()

        if isinstance(focus_item, QGraphicsProxyWidget):
            # 节点内部的控件正在被操作！无条件放行，让 Qt 原生处理打字、删字、复制文本
            super().keyPressEvent(event)
            return

        # ==========================================
        # 1. 撤销 / 重做 (Ctrl+Z / Ctrl+Y，也兼容 Ctrl+Shift+Z)
        # ==========================================
        if event.matches(QKeySequence.StandardKey.Undo):
            self.undo()
            event.accept()
            return

        if event.matches(QKeySequence.StandardKey.Redo):
            self.redo()
            event.accept()
            return

        # Ctrl+G：把当前框选/多选节点建立成锁定逻辑组。
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_G:
            self.create_group_from_selection()
            event.accept()
            return

        # ==========================================
        # 2. 删除动作 (Delete 或 Backspace)
        # ==========================================
        if (
            event.matches(QKeySequence.StandardKey.Delete)
            or event.key() == Qt.Key.Key_Backspace
        ):
            for item in self.scene().selectedItems():
                if isinstance(item, NodeItem):
                    self.scene().delete_node(item)
                elif isinstance(item, EdgeItem):
                    self.scene().delete_edge(item)
                elif isinstance(item, GroupItem):
                    self.scene().delete_group(item)
            self._history_timer.stop()
            self._capture_history_now()
            event.accept()
            return

        # ==========================================
        # 3. 复制动作 (Ctrl + C)
        # ==========================================
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_selection()
            event.accept()
            return

        # ==========================================
        # 4. 粘贴动作 (Ctrl + V)
        # ==========================================
        if event.matches(QKeySequence.StandardKey.Paste):
            self.paste_clipboard()
            event.accept()
            return

        # 其他按键交给父类默认处理
        super().keyPressEvent(event)

    # =========================================================
    # --- [核心实装]：无限画布与视角引擎 (Zoom & Pan) ---
    # =========================================================

    def drawBackground(self, painter: QPainter, rect: QRectF):
        """接管底层渲染：实现永远覆盖全视口、不随拖拽移动的壁纸"""
        painter.save()

        # 【核心黑魔法】：重置画笔坐标系！脱离无限物理世界，锁定到当前显示器屏幕！
        painter.resetTransform()

        # 获取当前窗口的真实物理尺寸
        target_rect = QRectF(self.viewport().rect())

        # 1. 先铺满当前主题的底色
        painter.fillRect(target_rect, Theme.SCENE_BG)

        # 2. 绘制自定义背景图
        scene = self.scene()
        if (
            hasattr(scene, "bg_pixmap")
            and scene.bg_pixmap
            and not scene.bg_pixmap.isNull()
        ):
            painter.setOpacity(scene.bg_opacity)

            source_rect = QRectF(scene.bg_pixmap.rect())

            # 【高级算法】：实现等比例缩放并裁剪填满屏幕 (类似 CSS 的 background-size: cover)
            view_ratio = target_rect.width() / target_rect.height()
            img_ratio = source_rect.width() / source_rect.height()

            if view_ratio > img_ratio:
                # 屏幕更宽：适配屏幕宽度，裁切掉图片的上下部分
                new_height = source_rect.width() / view_ratio
                y_offset = (source_rect.height() - new_height) / 2
                source_crop = QRectF(0, y_offset, source_rect.width(), new_height)
            else:
                # 屏幕更高：适配屏幕高度，裁切掉图片的左右部分
                new_width = source_rect.height() * view_ratio
                x_offset = (source_rect.width() - new_width) / 2
                source_crop = QRectF(x_offset, 0, new_width, source_rect.height())

            # 极速渲染：利用 Qt 原生底层直接映射裁切区域，拒绝使用 .scaled() 导致的拖拽卡顿！
            painter.drawPixmap(target_rect, scene.bg_pixmap, source_crop)

        painter.restore()

        # 3. 呼叫 Scene 绘制原有的网格线（因为 restore 了，画笔又回到了跟随拖拽的无限物理世界）
        super().drawBackground(painter, rect)

    def wheelEvent(self, event):
        """接管鼠标滚轮：实现以鼠标指针为锚点的丝滑缩放"""
        zoom_in_factor = 1.15
        zoom_out_factor = 1.0 / zoom_in_factor

        # 黑魔法：将坐标系转换的中心锚点强行绑定到鼠标当前位置
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

        # 判断滚轮方向 (向前推 > 0，向后滚 < 0)
        if event.angleDelta().y() > 0:
            zoom_factor = zoom_in_factor
            self._zoom *= zoom_in_factor
        else:
            zoom_factor = zoom_out_factor
            self._zoom *= zoom_out_factor

        # 极限保护：防止缩成一个点或者放大到像素爆炸导致内存溢出
        if self._zoom < 0.2:
            self._zoom = 0.2
            return
        if self._zoom > 3.0:
            self._zoom = 3.0
            return

        # 核心：调用 Qt 底层矩阵缩放
        self.scale(zoom_factor, zoom_factor)

    def mousePressEvent(self, event):
        """接管鼠标中键按下：开启平移状态"""
        if event.button() == Qt.MouseButton.MiddleButton:
            self._is_panning = True
            self._pan_start = event.pos()
            # 把鼠标光标变成一个小抓手
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """进阶：带动态边界增长的平移逻辑"""
        if self._is_panning:
            delta = event.pos() - self._pan_start

            # 执行平移
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x()
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y()
            )
            self._pan_start = event.pos()

            # --- [进阶技巧：动态边界增长] ---
            # 获取当前视口在场景中的坐标范围
            visible_rect = self.mapToScene(self.viewport().rect()).boundingRect()
            scene_rect = self.scene().sceneRect()

            # 阈值：距离边缘还剩 500 像素时触发扩张
            margin = 500
            padding = 2000  # 每次扩张的大小

            new_rect = QRectF(scene_rect)
            need_expand = False

            if visible_rect.left() < scene_rect.left() + margin:
                new_rect.setLeft(scene_rect.left() - padding)
                need_expand = True
            if visible_rect.right() > scene_rect.right() - margin:
                new_rect.setRight(scene_rect.right() + padding)
                need_expand = True
            if visible_rect.top() < scene_rect.top() + margin:
                new_rect.setTop(scene_rect.top() - padding)
                need_expand = True
            if visible_rect.bottom() > scene_rect.bottom() - margin:
                new_rect.setBottom(scene_rect.bottom() + padding)
                need_expand = True

            if need_expand:
                # 只有在真正需要时才更新场景尺寸，避免频繁重绘
                self.scene().setSceneRect(new_rect)

            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """接管鼠标中键松开：结束平移"""
        if event.button() == Qt.MouseButton.MiddleButton:
            self._is_panning = False
            # 恢复正常箭头
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)
