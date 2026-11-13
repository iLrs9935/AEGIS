import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QLineEdit, QSizePolicy
from qt_test_support import QtTestCase

from ui.graph_items import GroupItem, NodeItem
from ui.main_window import MainWindow, stop_event
from ui.node_inspector import NodeInspector


class UIInteractionTests(QtTestCase):
    def test_inspector_title_renames_selected_node(self):
        node = NodeItem("node-1", "等待时间", {"等待时长(s)": "2"}, "时间")
        inspector = NodeInspector()
        inspector.show_node(node)

        self.assertIsInstance(inspector.title, QLineEdit)
        self.assertFalse(inspector.title.isReadOnly())
        inspector.title.setText("等待兑换界面")
        inspector._commit_node_name()

        self.assertEqual(node.name, "等待兑换界面")
        inspector.close()

    def test_group_header_stays_within_group_width(self):
        group = GroupItem("group-1", "这是一个非常非常长的逻辑组名称")
        group.width = 250
        group.sync_header_geometry()
        group.widget.show()
        self.app.processEvents()

        self.assertEqual(group.widget.width(), 250)
        self.assertAlmostEqual(group.proxy.size().width(), 250.0)
        self.assertEqual(
            group.title_label.sizePolicy().horizontalPolicy(),
            QSizePolicy.Policy.Ignored,
        )
        self.assertLessEqual(group.toggle_cb.geometry().right(), group.widget.width())
        self.assertLessEqual(group.lock_cb.geometry().right(), group.widget.width())

    def test_background_controls_live_in_settings_menu(self):
        window = MainWindow()
        action_texts = [action.text() for action in window.background_menu.actions()]

        self.assertEqual(window.background_menu.title(), "🖼️ 画布背景")
        self.assertEqual(
            action_texts,
            ["📂 载入背景图...", "🎛️ 调整透明度...", "🗑️ 移除背景"],
        )
        window.close()

    def test_running_workflow_stops_before_blueprint_switch(self):
        window = MainWindow()
        target = os.path.join(window.workflow_dir, "2.json")
        window.engine.is_running = True
        if stop_event:
            stop_event.clear()

        try:
            with patch.object(
                window, "load_graph_from_json", return_value=True
            ) as load_graph, patch(
                "ui.main_window.QTimer.singleShot"
            ) as single_shot:
                window.handle_blueprint_jump(target)

                load_graph.assert_not_called()
                self.assertIsNotNone(window._pending_workflow_switch)
                if stop_event:
                    self.assertTrue(stop_event.is_set())

                window.engine.is_running = False
                window._on_dag_completed("cancelled", False)

                load_graph.assert_called_once_with(os.path.abspath(target))
                single_shot.assert_called_once_with(0, window.compile_and_run_dag)
                self.assertIsNone(window._pending_workflow_switch)
        finally:
            if stop_event:
                stop_event.clear()
            window.close()


if __name__ == "__main__":
    unittest.main()
