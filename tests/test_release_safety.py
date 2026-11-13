import copy
import io
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from core import config
from core.event_bus import bus
from functions.func_actions import stop_event
from nodes import NODE_REGISTRY
from nodes.notifications import bark_notification
from scripts.check_release import check_json_credentials, check_release, scan_text
from scripts.export_github import export_source
from ui.graph_items import NodeItem
from ui.main_window import MainWindow


ROOT = Path(__file__).resolve().parents[1]


class PrivateConfigTests(unittest.TestCase):
    def test_nested_references_use_environment_without_modifying_saved_config(self):
        original = {"nested": ["${ENV:AEGIS_TEST_VALUE}/suffix", False, 4]}
        before = copy.deepcopy(original)
        with patch.dict(os.environ, {"AEGIS_TEST_VALUE": "configured"}):
            resolved = config.resolve_config(original)
        self.assertEqual(resolved["nested"], ["configured/suffix", False, 4])
        self.assertEqual(original, before)

    def test_local_file_fallback_and_environment_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "config.local.json").write_text(
                json.dumps({"AEGIS_TEST_VALUE": "local"}), encoding="utf-8"
            )
            with patch.object(config, "application_directory", return_value=Path(directory)), patch.dict(os.environ, {}, clear=True):
                self.assertEqual(config.resolve_config("${ENV:AEGIS_TEST_VALUE}"), "local")
                with patch.dict(os.environ, {"AEGIS_TEST_VALUE": "environment"}):
                    self.assertEqual(config.resolve_config("${ENV:AEGIS_TEST_VALUE}"), "environment")
                with self.assertRaisesRegex(ValueError, "AEGIS_MISSING"):
                    config.resolve_config("${ENV:AEGIS_MISSING}")

    def test_invalid_local_configuration_does_not_disclose_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "config.local.json").write_text("private content", encoding="utf-8")
            with patch.object(config, "application_directory", return_value=Path(directory)), patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(ValueError) as caught:
                    config.private_setting("MISSING")
            self.assertNotIn("private content", str(caught.exception))

    def test_bark_reads_environment_and_never_requires_a_literal_in_the_graph(self):
        with patch.dict(os.environ, {"AEGIS_BARK_URL": "https://example.invalid/push"}), patch(
            "nodes.notifications.execute_bark_push", return_value=True
        ) as send:
            bark_notification({"Bark推送地址": ""}, {})
        self.assertEqual(send.call_args.args[0], "https://example.invalid/push")


class ReleaseAuditTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("git"), "Git is required for index audit")
    def test_audit_checks_staged_contents_even_if_working_file_is_clean(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "core").mkdir()
            source = root / "core" / "sample.py"
            source.write_text('VALUE = "' + "ghp_" + "A" * 36 + '"\n', encoding="utf-8")
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "add", "core/sample.py"], check=True)
            source.write_text("VALUE = 1\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(check_release(root), 1)
            self.assertIn("git-index-github-token", output.getvalue())

    def test_detects_realistic_credentials_but_accepts_explicit_placeholders(self):
        fake_github = "ghp_" + "A" * 36
        self.assertTrue(scan_text(fake_github))
        self.assertTrue(scan_text('api_key = "' + "A" * 32 + '"'))
        self.assertTrue(scan_text("https://api.day.app/" + "A" * 22))
        self.assertTrue(scan_text("https://example.com/?token=" + "A" * 32))
        self.assertFalse(scan_text("https://api.day.app/YOUR_KEY/"))
        self.assertFalse(scan_text('api_key = "${ENV:EXAMPLE_KEY}"'))
        self.assertTrue(check_json_credentials({"Bark推送地址": "https://example.invalid/device-key"}))
        self.assertFalse(check_json_credentials({"Bark推送地址": "${ENV:AEGIS_BARK_URL}"}))

    def test_export_excludes_local_workflows_and_detects_known_private_values(self):
        import zipfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "core").mkdir()
            source = root / "core" / "sample.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            (root / "workflows").mkdir()
            (root / "workflows" / "private.json").write_text("{}", encoding="utf-8")
            (root / "config.local.json").write_text(json.dumps({"PRIVATE_API_KEY": "test-private-value"}), encoding="utf-8")
            output = root / "source.zip"
            with redirect_stdout(io.StringIO()):
                export_source(root, output)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(set(archive.namelist()), {"core/sample.py", "SOURCE_MANIFEST.json"})
            source.write_text('VALUE = "test-private-value"\n', encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(check_release(root), 1)


class PublicWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_every_sample_loads_without_lost_nodes_edges_or_configuration(self):
        window = MainWindow()
        try:
            paths = sorted((ROOT / "examples" / "workflows").glob("*.json"))
            self.assertEqual(len(paths), 5)
            for path in paths:
                with self.subTest(path=path.name):
                    data = json.loads(path.read_text(encoding="utf-8"))
                    self.assertTrue(window.load_graph_from_json(str(path)))
                    items = {item.id: item for item in window.scene.items() if isinstance(item, NodeItem)}
                    self.assertEqual(len(items), len(data["nodes"]))
                    self.assertEqual(len(window.scene.connections), len(data["edges"]))
                    for node in data["nodes"]:
                        self.assertIn(node["type"], NODE_REGISTRY)
                        for key, value in node["config"].items():
                            self.assertEqual(items[node["id"]].get_config()[key], value)
        finally:
            self.close_window(window)

    def test_first_three_examples_complete_with_real_engine_and_expected_results(self):
        window = MainWindow()
        try:
            for filename, variable, expected in (
                ("01_hello_text.json", "greeting", "你好，AEGIS！"),
                ("02_value_router.json", "route_result", "找到目标"),
                ("03_array_loop.json", "loop_result", "三个元素均已处理"),
            ):
                stop_event.clear()
                self.assertTrue(window.load_graph_from_json(str(ROOT / "examples" / "workflows" / filename)))
                window.compile_and_run_dag()
                deadline = time.monotonic() + 5
                while window.engine.is_running and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(0.002)
                self.assertFalse(window.engine.is_running, filename)
                self.assertFalse(window.engine.execution_failed, filename)
                self.assertEqual(window.engine.global_context[variable], expected)
                if filename.startswith("03"):
                    self.assertEqual(window.engine.global_context["current_item"], "gamma")
        finally:
            self.close_window(window)

    @staticmethod
    def close_window(window):
        stop_event.set()
        window.engine.thread_pool.waitForDone(3000)
        window.close()
        bus.node_status_changed.disconnect(window.engine._on_node_status_changed)
        bus.log_emitted.disconnect(window.append_log)
        bus.dag_completed.disconnect(window._on_dag_completed)
        bus.blueprint_jump_requested.disconnect(window.handle_blueprint_jump)
        stop_event.clear()
