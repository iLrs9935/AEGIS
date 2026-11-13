import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from core.event_bus import bus
from nodes import NODE_REGISTRY
from ui.i18n import ENGLISH, QComboBox, language, set_language, tr
from ui.graph_items import NodeItem, NodeWidget, RouteRulesEditor
from ui.main_window import MainWindow


class LocalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.previous = language()
        set_language("en")

    def tearDown(self):
        set_language(self.previous)

    def test_every_registered_type_category_parameter_and_choice_has_english_text(self):
        for name, meta in NODE_REGISTRY.items():
            labels = [name, meta["category"], *meta["schema"].get("__out_ports__", [])]
            for key, value in meta["schema"].items():
                if key.startswith("__"):
                    continue
                labels.append(key)
                if isinstance(value, list):
                    labels.extend(value)
            for text in labels:
                if any("\u4e00" <= ch <= "\u9fff" for ch in str(text)):
                    self.assertIn(text, ENGLISH, text)

    def test_all_node_forms_keep_original_configuration_in_both_languages(self):
        for name, meta in NODE_REGISTRY.items():
            schema = {key: value for key, value in meta["schema"].items() if not key.startswith("__")}
            form = NodeWidget(schema)
            expected = form.get_config()
            set_language("zh")
            self.assertEqual(form.get_config(), expected, name)
            set_language("en")
            form.set_config(expected)
            self.assertEqual(form.get_config(), expected, name)
            form.deleteLater()

    def test_combobox_and_router_show_english_but_return_canonical_values(self):
        combo = QComboBox()
        combo.addItems(["前台物理(SendInput)", "后台消息(PostMessage)"])
        combo.setCurrentIndex(1)
        self.assertEqual(combo.itemText(1), "Background (PostMessage)")
        self.assertEqual(combo.currentText(), "后台消息(PostMessage)")
        editor = RouteRulesEditor()
        editor.rows[0]["operator"].setCurrentText("大于")
        self.assertEqual(editor.get_value()[0]["operator"], "大于")
        set_language("zh")
        self.assertEqual(combo.itemText(1), "后台消息(PostMessage)")
        self.assertEqual(editor.get_value()[0]["operator"], "大于")
        combo.deleteLater()
        editor.deleteLater()

    def test_live_switch_preserves_graph_config_name_selection_and_undo_history(self):
        window = MainWindow()
        try:
            path = Path(__file__).resolve().parents[1] / "examples/workflows/02_value_router.json"
            self.assertTrue(window.load_graph_from_json(str(path)))
            node = next(item for item in window.scene.items() if isinstance(item, NodeItem) and item.id == "router")
            node.setSelected(True)
            snapshot = window.view._serialize_scene()
            history = list(window.view._history)
            with patch("ui.i18n.application_directory") as root:
                # Persistence is tested separately; no real user settings are changed.
                root.return_value = Path(os.devnull) / "unwritable"
                window.set_ui_language("zh")
                self.assertEqual(window.btn_run.text(), "▶ 运行")
                window.set_ui_language("en")
            self.assertEqual(window.btn_run.text(), "▶ Run")
            self.assertEqual(window.inspector.title.text(), "Route value")
            window.inspector._commit_node_name()
            self.assertEqual(node.name, "按 found 分支")
            self.assertEqual(window.view._serialize_scene(), snapshot)
            self.assertEqual(window.view._history, history)
            self.assertTrue(node.isSelected())
        finally:
            window.close()
            bus.node_status_changed.disconnect(window.engine._on_node_status_changed)
            bus.log_emitted.disconnect(window.append_log)
            bus.dag_completed.disconnect(window._on_dag_completed)
            bus.blueprint_jump_requested.disconnect(window.handle_blueprint_jump)

    def test_unknown_user_text_is_preserved(self):
        self.assertEqual(tr("用户自行填写的业务数据 123"), "用户自行填写的业务数据 123")
