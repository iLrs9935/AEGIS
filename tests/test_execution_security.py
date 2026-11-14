"""Engine/UI security integration. All effectful nodes use test doubles."""
import json
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch

from qt_test_support import QtTestCase
from core.engine import DAGEngine, NodeWorker
from core.event_bus import bus
from core.security import NODE_CAPABILITIES, READ_ONLY, PermissionDenied
from functions.func_actions import stop_event
from nodes import NODE_REGISTRY
from ui.main_window import MainWindow


class ImmediatePool:
    def start(self, worker):
        worker.run()


class ExecutionSecurityTests(QtTestCase):
    def setUp(self):
        stop_event.clear()
        self.engines = []

    def tearDown(self):
        for engine in self.engines:
            bus.run_node_status_changed.disconnect(engine._on_run_node_status_changed)
            bus.node_status_changed.disconnect(engine._on_node_status_changed)
        self.app.processEvents()

    def engine(self, name, source="local", config=None):
        engine = DAGEngine()
        engine.thread_pool = ImmediatePool()
        engine.load_from_ui({"n": {"name": name, "config": config or {}}}, [], source=source)
        self.engines.append(engine)
        return engine

    def test_registry_classification_is_complete_and_unknown_nodes_fail_closed(self):
        self.assertEqual(set(NODE_REGISTRY), set(NODE_CAPABILITIES))
        for name, meta in NODE_REGISTRY.items():
            self.assertEqual(meta["capabilities"], NODE_CAPABILITIES[name])
        engine = self.engine("unknown")
        self.assertTrue(engine.review_execution().unknown)
        self.assertFalse(engine.start_execution())

    def test_each_effectful_node_requires_authorization_for_all_origins(self):
        for name, caps in NODE_CAPABILITIES.items():
            if caps == {READ_ONLY}:
                continue
            for source in ("local", "external", "ai"):
                with self.subTest(name=name, source=source):
                    effect = Mock(return_value={"status": "Success"})
                    with patch.dict(NODE_REGISTRY[name], {"func": effect}):
                        engine = self.engine(name, source)
                        self.assertEqual(engine.review_execution().source, source)
                        self.assertFalse(engine.start_execution())
                        effect.assert_not_called()
                        engine.authorize_execution(engine.review_execution().required)
                        self.assertTrue(engine.start_execution())
                        effect.assert_called_once()
                        self.assertFalse(engine.execution_failed)
                        engine._finish_if_idle()
                        # Approval does not silently authorize a subsequent run.
                        self.assertFalse(engine.start_execution())

    def test_read_only_workflow_needs_no_grant(self):
        engine = self.engine("文本输入", "external", {"文本内容": "hello", "存入变量名": "result"})
        self.assertTrue(engine.start_execution())
        self.assertEqual(engine.global_context["result"], "hello")

    def test_review_exposes_current_position_and_delete_all_effects(self):
        engine = self.engine("连续物理点击", config={"坐标模式": "当前位置"})
        self.assertIn("当前位置", engine.review_execution().describe())
        engine = self.engine("删除记忆", config={"目标键名 (输入 * 擦除全部)": "*"})
        self.assertIn("删除全部持久化记忆", engine.review_execution().describe())

    def test_safe_power_rejects_indirect_process_keyboard_file_network_and_jump(self):
        with patch("functions.func_system.SAFE_POWER_MODE", True):
            for name, caps in NODE_CAPABILITIES.items():
                if caps == {READ_ONLY}:
                    continue
                with self.subTest(name=name), patch.dict(NODE_REGISTRY[name], {"func": Mock()}) as registry:
                    engine = self.engine(name)
                    engine.authorize_execution(engine.review_execution().required)
                    self.assertFalse(engine.start_execution())
                    registry["func"].assert_not_called()

    def test_direct_worker_and_forged_config_cannot_bypass_engine(self):
        effect = Mock(return_value={"status": "Success"})
        with patch.dict(NODE_REGISTRY["启动程序"], {"func": effect}):
            NodeWorker("n", "启动程序", {}, {}).run()
            effect.assert_not_called()
            engine = self.engine("启动程序", config={"程序路径": "approved.exe"})
            policy = engine.authorize_execution(engine.review_execution().required)
            forged = {"name": "启动程序", "config": {"程序路径": "other.exe"}}
            NodeWorker("n", "启动程序", forged["config"], {}, policy=policy,
                       fingerprint=policy.fingerprint, node_spec=forged).run()
            effect.assert_not_called()

    def test_authorization_is_invalidated_by_configuration_or_topology_changes(self):
        for change in ("config", "edge"):
            engine = self.engine("启动程序")
            engine.authorize_execution(engine.review_execution().required)
            if change == "config":
                engine.node_data_map["n"]["config"]["启动参数"] = "changed"
            else:
                engine._edges_data.append(("n", "OUT", "n", "IN"))
            self.assertFalse(engine.start_execution())

    def test_runtime_check_rejects_change_after_root_node_and_revoked_safe_mode(self):
        for mutate_policy in (False, True):
            engine = DAGEngine()
            self.engines.append(engine)
            queued = []
            engine.thread_pool = Mock(start=queued.append)
            engine.load_from_ui({
                "root": {"name": "文本输入", "config": {}},
                "effect": {"name": "启动程序", "config": {}},
            }, [("root", "文本输出", "effect", "IN")])
            engine.authorize_execution(engine.review_execution().required)
            self.assertTrue(engine.start_execution())
            with patch.dict(NODE_REGISTRY["启动程序"], {"func": Mock()}) as registry:
                queued.pop(0).run()
                self.assertEqual(len(queued), 1)
                worker = queued.pop(0)
                if mutate_policy:
                    worker.config["启动参数"] = "changed"
                    worker.run()
                else:
                    with patch("functions.func_system.SAFE_POWER_MODE", True):
                        worker.run()
                registry["func"].assert_not_called()
                self.assertTrue(engine.execution_failed)

    def test_branch_and_feedback_containing_high_risk_node_are_reviewed_before_any_work(self):
        engine = DAGEngine()
        self.engines.append(engine)
        engine.thread_pool = ImmediatePool()
        engine.load_from_ui({
            "root": {"name": "文本输入", "config": {}},
            "risk": {"name": "结束进程", "config": {}},
        }, [("root", "unused-branch", "risk", "IN"), ("risk", "OUT", "root", "IN")])
        with patch.dict(NODE_REGISTRY["文本输入"], {"func": Mock()}) as registry:
            self.assertFalse(engine.start_execution())
            registry["func"].assert_not_called()
        self.assertIn("risk", engine.review_execution().describe())

    def test_nested_workflow_gets_fresh_review_and_never_inherits_grants(self):
        parent = self.engine("运行新图纸")
        parent.authorize_execution(parent.review_execution().required)
        child = self.engine("系统休眠", "external")
        with patch.dict(NODE_REGISTRY["系统休眠"], {"func": Mock()}) as registry:
            self.assertFalse(child.start_execution())
            registry["func"].assert_not_called()


class WorkflowReviewUITests(QtTestCase):
    def setUp(self):
        stop_event.clear()
        self.window = MainWindow()

    def tearDown(self):
        window = self.window
        window.close()
        bus.node_status_changed.disconnect(window.engine._on_node_status_changed)
        bus.run_node_status_changed.disconnect(window.engine._on_run_node_status_changed)
        bus.log_emitted.disconnect(window.append_log)
        bus.dag_completed.disconnect(window._on_dag_completed)
        bus.run_dag_completed.disconnect(window._on_run_dag_completed)
        bus.blueprint_jump_requested.disconnect(window.handle_blueprint_jump)
        bus.run_blueprint_jump_requested.disconnect(window._on_run_blueprint_jump)

    def write(self, root, nodes, meta=None):
        path = Path(root) / "workflow.json"
        path.write_text(json.dumps({"nodes": nodes, "edges": [], "meta": meta or {}}), encoding="utf-8")
        return path

    def test_import_cannot_self_grant_and_rejection_has_no_effect(self):
        with tempfile.TemporaryDirectory() as root:
            path = self.write(root, [{"id": "risk", "name": "launch", "type": "启动程序", "config": {}}],
                              {"source": "local", "trusted": True, "permissions": ["process_control"]})
            self.assertTrue(self.window.load_graph_from_json(str(path)))
            self.assertEqual(self.window.workflow_source, "external")
            with patch.object(self.window, "_confirm_execution_review", return_value=False) as confirm, patch(
                "nodes.system.execute_start_process"
            ) as effect:
                self.assertFalse(self.window.compile_and_run_dag())
                confirm.assert_called_once()
                effect.assert_not_called()

    def test_review_dialog_defaults_to_no(self):
        from PyQt6.QtWidgets import QMessageBox
        from core.security import review_workflow
        review = review_workflow({"x": {"name": "启动程序", "config": {}}}, [])
        with patch("ui.main_window.QMessageBox.warning", return_value=QMessageBox.StandardButton.No) as dialog:
            self.assertFalse(self.window._confirm_execution_review(review))
            self.assertEqual(dialog.call_args.args[-1], QMessageBox.StandardButton.No)
            self.assertIn("启动程序", dialog.call_args.args[2])
            self.assertIn("process_control", dialog.call_args.args[2])

    def test_foreign_completion_cannot_switch_pending_workflow(self):
        self.window.engine._managed = True
        self.window.engine.run_id = "owned-run"
        self.window._pending_workflow_switch = ("child.json", True, 0)
        with patch.object(self.window, "_apply_workflow_switch") as switch:
            bus.dag_completed.emit("finished", True)
            bus.run_dag_completed.emit("foreign-run", "finished", True)
            switch.assert_not_called()
            bus.run_dag_completed.emit("owned-run", "finished", True)
            switch.assert_called_once_with("child.json", True, 0)

    def test_foreign_blueprint_jump_is_ignored_and_owned_jump_routes(self):
        self.window.engine.run_id = "owned-run"
        self.window.engine.is_running = True
        try:
            with patch.object(self.window, "handle_blueprint_jump") as jump:
                bus.run_blueprint_jump_requested.emit("foreign-run", "foreign.json")
                jump.assert_not_called()
                bus.run_blueprint_jump_requested.emit("owned-run", "child.json")
                jump.assert_called_once_with("child.json")
        finally:
            self.window.engine.is_running = False

    def test_click_migration_roundtrip_preserves_ids_edges_and_explicit_mode(self):
        with tempfile.TemporaryDirectory() as root:
            path = self.write(root, [{"id": "old", "name": "click", "type": "连续物理点击", "config": {"点击次数": "2"}}])
            self.assertTrue(self.window.load_graph_from_json(str(path)))
            self.assertTrue(self.window.workflow_notices)
            self.window.save_graph_to_json(str(path))
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["nodes"][0]["id"], "old")
            self.assertEqual(saved["nodes"][0]["config"]["坐标模式"], "指定坐标")
            self.assertEqual(saved["meta"]["click_mode_version"], 1)
            self.assertTrue(self.window.load_graph_from_json(str(path)))
            self.assertEqual(self.window.workflow_notices, [])

    def test_unknown_nodes_duplicate_ids_and_bad_edges_are_rejected_without_replacing_canvas(self):
        with tempfile.TemporaryDirectory() as root:
            valid = [{"id": "ok", "name": "text", "type": "文本输入", "config": {}}]
            path = self.write(root, valid)
            self.assertTrue(self.window.load_graph_from_json(str(path)))
            before = self.window.view._serialize_scene()
            for nodes in ([{"id": "unknown", "type": "arbitrary"}], valid + valid):
                path = self.write(root, nodes)
                self.assertFalse(self.window.load_graph_from_json(str(path)))
                self.assertEqual(self.window.view._serialize_scene(), before)
            path.write_text(json.dumps({"nodes": valid, "edges": [{"src_id": "missing", "tgt_id": "ok", "tgt_port": "IN"}]}), encoding="utf-8")
            self.assertFalse(self.window.load_graph_from_json(str(path)))
            self.assertEqual(self.window.view._serialize_scene(), before)
            for change in ({"meta": []}, {"nodes": [{**valid[0], "x": float("inf")}]},
                           {"edges": [{"src_id": "ok", "src_port": "unknown", "tgt_id": "ok", "tgt_port": "IN"}]}):
                path.write_text(json.dumps({"nodes": valid, "edges": [], **change}), encoding="utf-8")
                self.assertFalse(self.window.load_graph_from_json(str(path)))
                self.assertEqual(self.window.view._serialize_scene(), before)
