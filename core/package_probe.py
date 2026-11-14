"""Bounded packaged-EXE probe: only built-in text/data examples may execute."""
import hashlib
import json
from pathlib import Path
import platform
import sys
import time


def verify_package(app, report_path):
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Package verification requires the actual frozen executable")
    from core.event_bus import bus
    from ui.main_window import MainWindow

    scenarios = []
    window = MainWindow()
    try:
        for filename, variable, expected in (
            ("01_hello_text.json", "greeting", "你好，AEGIS！"),
            ("02_value_router.json", "route_result", "找到目标"),
            ("03_array_loop.json", "loop_result", "三个元素均已处理"),
        ):
            path = Path(sys._MEIPASS) / "workflows" / filename
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            if not window.load_graph_from_json(str(path)):
                raise RuntimeError(f"Cannot load packaged example: {filename}")
            if not window.compile_and_run_dag():
                raise RuntimeError(f"Cannot start packaged example: {filename}")
            deadline = time.monotonic() + 10
            while window.engine.is_running and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.001)
            if window.engine.is_running or window.engine.execution_failed:
                raise RuntimeError(f"Packaged execution failed/timed out: {filename}")
            if window.engine.global_context.get(variable) != expected:
                raise RuntimeError(f"Unexpected packaged output: {filename}")
            if before != hashlib.sha256(path.read_bytes()).hexdigest():
                raise RuntimeError("Packaged example changed during execution")
            scenarios.append({"name": filename, "outcome": "passed", "workflow_unchanged": True})
        # A no-effect power configuration is deliberately used: even a broken
        # gate here cannot hibernate or terminate the validation host.
        window.engine.load_from_ui({"deny": {"name": "系统休眠", "config": {"执行动作": "保留终端(不休眠)"}}}, [], source="external")
        if window.engine.start_execution():
            raise RuntimeError("Packaged permission boundary admitted an unapproved system node")
        scenarios.append({"name": "unapproved-system-node", "outcome": "passed", "actual_power_operation": False})
        data = {
            "schema_version": 1, "packaged": True,
            "python": platform.python_version(), "platform": platform.platform(),
            "executable_sha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
            "scenarios": scenarios,
            "unverified": ["Bark delivery", "OK-WW/game", "real mouse/keyboard", "hibernation", "optional model/browser"],
        }
        with Path(report_path).open("x", encoding="utf-8") as target:
            json.dump(data, target, ensure_ascii=False, indent=2)
        return 0
    finally:
        window.engine.thread_pool.waitForDone(5000)
        window.close()
        bus.run_node_status_changed.disconnect(window.engine._on_run_node_status_changed)
        bus.node_status_changed.disconnect(window.engine._on_node_status_changed)
        bus.log_emitted.disconnect(window.append_log)
        bus.dag_completed.disconnect(window._on_dag_completed)
        bus.run_dag_completed.disconnect(window._on_run_dag_completed)
        bus.blueprint_jump_requested.disconnect(window.handle_blueprint_jump)
        bus.run_blueprint_jump_requested.disconnect(window._on_run_blueprint_jump)
