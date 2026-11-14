"""Deterministic thread/Qt integration tests; no desktop or external effects."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
import time
from unittest.mock import patch

from qt_test_support import QtTestCase
from core.context import ContextConflict, ExecutionContext
from core.engine import DAGEngine
from core.event_bus import bus
from functions.func_actions import stop_event
from functions.func_logic import check_logic_and, check_logic_or
from nodes import NODE_REGISTRY
from nodes.logic import logic_iterator_node
from nodes.okww import STATE_KEY, initialise_okww_monitor


class ContextConcurrencyTests(QtTestCase):
    def setUp(self):
        stop_event.clear()

    def test_different_keys_and_detached_nested_values(self):
        context = ExecutionContext()
        barrier = Barrier(8)
        def write(index):
            barrier.wait(timeout=3)
            for counter in range(100):
                context[str(index)] = {"items": [counter]}
        with ThreadPoolExecutor(8) as pool:
            list(pool.map(write, range(8)))
        self.assertEqual(context.snapshot(), {str(i): {"items": [99]} for i in range(8)})
        original = {"items": [1]}
        context["x"] = original
        original["items"].append(2)
        context["x"]["items"].append(3)
        self.assertEqual(context["x"], {"items": [1]})

    def test_atomic_compound_increment_and_consistent_reads(self):
        context = ExecutionContext()
        context.update(counter=0, mirror=0)
        barrier = Barrier(8)
        def increment(_):
            barrier.wait(timeout=3)
            for _ in range(100):
                def transform(data):
                    data["counter"] += 1
                    data["mirror"] = data["counter"]
                context.mutate(transform)
                view = context.snapshot()
                self.assertEqual(view["counter"], view["mirror"])
        with ThreadPoolExecutor(8) as pool:
            list(pool.map(increment, range(8)))
        self.assertEqual(context["counter"], 800)

    def test_same_variable_writes_are_complete_last_writer_wins(self):
        context = ExecutionContext()
        barrier = Barrier(4)
        def write(index):
            barrier.wait(timeout=3)
            for _ in range(100):
                context["shared"] = [index] * 50
                value = context["shared"]
                self.assertEqual(len(set(value)), 1)
        with ThreadPoolExecutor(4) as pool:
            list(pool.map(write, range(4)))
        self.assertIn(context["shared"][0], range(4))

    def test_clear_invalidates_inflight_commit_and_close_rejects_late_write(self):
        context = ExecutionContext()
        entered, release = Event(), Event()
        def edit():
            with self.assertRaises(ContextConflict):
                with context.edit("state") as data:
                    data["state"] = {"done": True}
                    entered.set()
                    self.assertTrue(release.wait(3))
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(edit)
            self.assertTrue(entered.wait(3))
            context.clear()
            release.set()
            future.result(timeout=3)
        self.assertEqual(context.snapshot(), {})
        context.close()
        with self.assertRaises(ContextConflict):
            context["late"] = True

    def test_state_reservation_never_holds_mutex_during_callback(self):
        context = ExecutionContext()
        context["state"] = {"attempt": 0}
        with context.edit("state") as data:
            with ThreadPoolExecutor(1) as pool:
                pool.submit(context.__setitem__, "other", True).result(timeout=3)
            with self.assertRaises(ContextConflict):
                context["state"] = {}
            with self.assertRaises(ContextConflict):
                with context.edit("state"):
                    self.fail("Conflicting state edit was admitted")
            data["state"]["attempt"] += 1
        self.assertEqual(context["state"], {"attempt": 1})
        self.assertTrue(context["other"])

    def test_failed_state_edit_releases_reservation_without_partial_commit(self):
        context = ExecutionContext()
        context["state"] = [1]
        with self.assertRaises(OSError):
            with context.edit("state") as data:
                data["state"].append(2)
                raise OSError("external failure")
        with context.edit("state") as data:
            data["state"].append(3)
        self.assertEqual(context["state"], [1, 3])

    def test_parallel_iterator_pops_have_no_duplicates_or_lost_queue_updates(self):
        context = ExecutionContext()
        context["queue"] = list(range(40))
        barrier = Barrier(8)
        def consume(_):
            barrier.wait(timeout=3)
            return [logic_iterator_node(
                {"目标数组变量名": "queue"},
                {"__global_context__": context, "__node_id__": "same"},
            )["value"] for _ in range(5)]
        with ThreadPoolExecutor(8) as pool:
            values = [value for batch in pool.map(consume, range(8)) for value in batch]
        self.assertEqual(sorted(values), list(range(40)))
        self.assertEqual(context["queue"], [])

    def test_logic_gates_use_one_snapshot(self):
        context = ExecutionContext()
        context.update(a=True, b=True)
        with patch.object(context, "get", side_effect=AssertionError("mixed reads")):
            self.assertTrue(check_logic_and(context, ["a", "b"]))
            self.assertTrue(check_logic_or(context, ["a", "b"]))

    def test_engine_rejects_cross_thread_lifecycle_changes(self):
        engine = DAGEngine()
        try:
            with ThreadPoolExecutor(1) as pool:
                for operation in (engine.start_execution,
                                  lambda: engine.load_from_ui({}, []),
                                  engine.authorize_execution):
                    with self.assertRaisesRegex(RuntimeError, "owning Qt thread"):
                        pool.submit(operation).result(timeout=3)
        finally:
            bus.run_node_status_changed.disconnect(engine._on_run_node_status_changed)
            bus.node_status_changed.disconnect(engine._on_node_status_changed)

    def test_same_node_reentry_cannot_retire_or_replace_live_worker_context(self):
        engine = DAGEngine()
        queued = []
        engine.thread_pool = type("QueuePool", (), {"start": lambda self, worker: queued.append(worker)})()
        try:
            engine.load_from_ui({"same": {"name": "文本输入", "config": {"文本内容": "done", "存入变量名": "result"}}}, [])
            self.assertTrue(engine.start_execution())
            context = engine.global_context
            engine._dispatch_node("same")
            self.assertTrue(engine.execution_failed)
            self.assertEqual(len(queued), 1)
            engine._finish_if_idle()
            self.assertTrue(engine.is_running)
            context["still-live"] = True
            queued.pop().run()
            engine._finish_if_idle()
            self.assertFalse(engine.is_running)
            self.assertEqual(context["result"], "done")
            with self.assertRaises(ContextConflict):
                context["late"] = True
        finally:
            bus.run_node_status_changed.disconnect(engine._on_run_node_status_changed)
            bus.node_status_changed.disconnect(engine._on_node_status_changed)

    def test_okww_state_is_committed_and_unrelated_keys_remain_accessible(self):
        context = ExecutionContext()
        def inspect(*args):
            with ThreadPoolExecutor(1) as pool:
                pool.submit(context.__setitem__, "callback", True).result(timeout=3)
            return []
        with patch("nodes.okww._relevant_processes", side_effect=inspect), patch(
            "nodes.okww.snapshot_log_offsets", return_value={}
        ):
            result = initialise_okww_monitor({}, {"__global_context__": context})
        self.assertEqual(result["active_port"], "允许启动")
        self.assertEqual(context[STATE_KEY]["attempt"], 1)
        self.assertTrue(context["callback"])

    def test_parallel_nodes_and_same_ids_in_concurrent_engines_are_isolated(self):
        engines = [DAGEngine(), DAGEngine()]
        entered = Barrier(5)
        release = Event()
        def execute(config, inputs):
            entered.wait(timeout=4)
            if not release.wait(4):
                raise AssertionError("Worker was not released")
            inputs["__global_context__"][config["key"]] = config["value"]
            return {"status": "Success", "value": config["value"]}
        try:
            with patch.dict(NODE_REGISTRY["文本输入"], {"func": execute}):
                for index, engine in enumerate(engines):
                    engine.load_from_ui({
                        node_id: {"name": "文本输入", "config": {"key": node_id, "value": index}}
                        for node_id in ("same-a", "same-b")
                    }, [])
                    self.assertTrue(engine.start_execution())
                entered.wait(timeout=4)
                # Public/foreign/stale statuses cannot release live nodes.
                bus.node_status_changed.emit("same-a", "Success", "{}")
                bus.run_node_status_changed.emit("obsolete-run", "same-b", "Failed", "")
                self.app.processEvents()
                for engine in engines:
                    self.assertEqual(engine.active_nodes, {"same-a", "same-b"})
                release.set()
                deadline = time.monotonic() + 5
                while any(e.is_running for e in engines) and time.monotonic() < deadline:
                    self.app.processEvents()
                for index, engine in enumerate(engines):
                    self.assertFalse(engine.is_running)
                    self.assertFalse(engine.execution_failed)
                    self.assertEqual(engine.global_context.snapshot(), {"same-a": index, "same-b": index})
                    old = engine.global_context
                    engine.load_from_ui({"new": {"name": "等待时间", "config": {"等待时长(s)": "0"}}}, [])
                    self.assertTrue(engine.start_execution())
                    with self.assertRaises(ContextConflict):
                        old["late"] = True
                deadline = time.monotonic() + 5
                while any(e.is_running for e in engines) and time.monotonic() < deadline:
                    self.app.processEvents()
        finally:
            release.set()
            for engine in engines:
                engine.thread_pool.waitForDone(5000)
                bus.run_node_status_changed.disconnect(engine._on_run_node_status_changed)
                bus.node_status_changed.disconnect(engine._on_node_status_changed)
