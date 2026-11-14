"""Keep the published bilingual workflow examples loadable and executable."""
import json
from pathlib import Path
import re
import tempfile
import time

from qt_test_support import QtTestCase
from core.event_bus import bus
from core.signals import BUILTIN_VALUE_TYPES
from core.workflow import output_ports, validate_document
from functions.func_actions import stop_event
from nodes import NODE_REGISTRY
from ui.main_window import MainWindow

ROOT = Path(__file__).resolve().parents[1]
GUIDES = ("LLM_WORKFLOW_QUICKSTART.md", "LLM_WORKFLOW_QUICKSTART.en.md")


def examples(filename):
    text = (ROOT / "docs" / filename).read_text(encoding="utf-8")
    return [json.loads(block) for block in re.findall(r"```json\s*\n(.*?)\n```", text, re.S)]


def dispose(window):
    window.engine.thread_pool.waitForDone(5000)
    window.close()
    for signal, slot in (
        (bus.node_status_changed, window.engine._on_node_status_changed),
        (bus.run_node_status_changed, window.engine._on_run_node_status_changed),
        (bus.log_emitted, window.append_log),
        (bus.dag_completed, window._on_dag_completed),
        (bus.run_dag_completed, window._on_run_dag_completed),
        (bus.blueprint_jump_requested, window.handle_blueprint_jump),
        (bus.run_blueprint_jump_requested, window._on_run_blueprint_jump),
    ):
        signal.disconnect(slot)


class LLMQuickstartTests(QtTestCase):
    def test_bilingual_examples_keep_canonical_schema_topology_and_load_without_loss(self):
        documents = [examples(name) for name in GUIDES]
        self.assertEqual([len(items) for items in documents], [2, 2])
        for zh, en in zip(*documents):
            self.assertEqual(zh["edges"], en["edges"])
            self.assertEqual([n["id"] for n in zh["nodes"]], [n["id"] for n in en["nodes"]])
        window = MainWindow()
        try:
            with tempfile.TemporaryDirectory() as directory:
                for language_documents in documents:
                    for data in language_documents:
                        validate_document(data, NODE_REGISTRY)
                        for node in data["nodes"]:
                            meta = NODE_REGISTRY[node["type"]]
                            self.assertEqual(node["category"], meta["category"])
                            self.assertLessEqual(set(node["config"]), set(meta["schema"]))
                            self.assertEqual(set(node["signal_config"]["outputs"]), output_ports(node["type"], node["config"], NODE_REGISTRY))
                            self.assertIn(node["signal_config"]["input"]["type"], BUILTIN_VALUE_TYPES)
                        path = Path(directory) / "example.json"
                        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                        self.assertTrue(window.load_graph_from_json(str(path)))
                        serialized = window.view._serialize_scene()
                        self.assertEqual(len(serialized["nodes"]), len(data["nodes"]))
                        self.assertEqual(len(window.scene.connections), len(data["edges"]))
        finally:
            dispose(window)

    def test_text_examples_execute_in_both_languages_without_external_actions(self):
        window = MainWindow()
        try:
            with tempfile.TemporaryDirectory() as directory:
                for name in GUIDES:
                    data = examples(name)[0]
                    path = Path(directory) / "text.json"
                    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                    stop_event.clear()
                    self.assertTrue(window.load_graph_from_json(str(path)))
                    self.assertTrue(window.compile_and_run_dag())
                    deadline = time.monotonic() + 5
                    while window.engine.is_running and time.monotonic() < deadline:
                        self.app.processEvents()
                    self.assertFalse(window.engine.is_running)
                    self.assertFalse(window.engine.execution_failed)
                    self.assertEqual(window.engine.global_context["greeting"], data["nodes"][0]["config"]["文本内容"])
        finally:
            dispose(window)
