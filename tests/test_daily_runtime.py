"""Real Qt UI, thread pool, node functions, routing and log reads; fake HAL only."""
import json
import os
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QThreadPool
from qt_test_support import QtTestCase
from core.event_bus import bus
from core.run_log import RunLog
from functions.func_actions import stop_event
from functions.func_okww import classify_log_update, SUCCESS_MARKER
from nodes import okww
from ui.main_window import MainWindow
from ui.graph_items import NodeItem


class DailyRuntimeTests(QtTestCase):
    def run_daily(self, scenario, daily_completion='Daily Task Completed'):
        stop_event.clear()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outer, inner = root / 'outer', root / 'inner'
            outer.mkdir()
            inner.mkdir()
            log_path = inner / 'ok-script.log'
            log_path.write_text('', encoding='utf-8')
            data = json.loads((Path(__file__).resolve().parents[1] / 'tests/fixtures/daily.json').read_text(encoding='utf-8'))
            for node in data['nodes']:
                if node['type'] == 'OK-WW监控初始化':
                    node['config']['OK-WW日志目录'] = str(outer)
                    node['config']['OK-WW内部日志目录'] = str(inner)
                    script = root / 'main.py'
                    script.touch()
                    node['config']['OK-WW主脚本路径'] = str(script)
                    node['config']['OK-WW Python路径'] = str(root / 'pythonw.exe')
                if node['type'] == 'OK-WW任务监控':
                    node['config']['退出日志宽限(s)'] = '0'
                    node['config']['更新界面检查间隔(轮询次数)'] = '1'
            workflow = root / 'daily.json'
            workflow.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            calls = {'launches': 0, 'inventory': 0, 'paths': []}
            worker = {'pid': 123, 'creation_date': 'NEW', 'role': 'okww_worker'}

            def launch(*args, **kwargs):
                calls['launches'] += 1
                calls['paths'].append(args[0])
                calls['inventory'] = 0
                if scenario == 'update_recovery' and calls['launches'] == 1:
                    stamp = datetime.now().isoformat(sep=' ', timespec='microseconds')
                    (outer / 'app.today').write_text(f'{stamp} INFO Auto Update to version v3.7.11 success.\n', encoding='utf-8')
                if scenario == 'success' or (scenario in {'update_recovery', 'crash_recovery'} and calls['launches'] == 2):
                    stamp = datetime.now().isoformat(sep=' ', timespec='microseconds')
                    with log_path.open('a', encoding='utf-8') as handle:
                        handle.write(f'{stamp} INFO DailyTask:{daily_completion}\n{stamp} INFO TaskExecutor:{SUCCESS_MARKER}\n')
                return True, 123

            def inspect(*args, **kwargs):
                if scenario == 'busy':
                    return [worker]
                if not calls['launches'] or scenario == 'success':
                    return []
                if scenario in {'update_recovery', 'crash_recovery'}:
                    state = window.engine.global_context.get(okww.STATE_KEY, {})
                    if state.get('terminal_state') != 'running' or calls['launches'] == 2:
                        return []
                    if scenario == 'update_recovery':
                        return [{'pid': 321, 'creation_date': 'NEW', 'role': 'okww_launcher'}]
                    calls['inventory'] += 1
                    return [worker, {'pid': 456, 'creation_date': 'NEW', 'role': 'game'}] if calls['inventory'] == 1 else [worker]
                calls['inventory'] += 1
                if scenario == 'update' and calls['inventory'] == 1:
                    return [worker, {'pid': 456, 'creation_date': 'NEW', 'role': 'game'}]
                return [worker] if calls['inventory'] == 1 else []

            window = MainWindow()
            pool = QThreadPool()
            window.engine.thread_pool = pool
            recorder = RunLog(root / 'records')
            self.assertTrue(window.load_graph_from_json(str(workflow)))
            self.assertEqual(len(window.scene.connections), len(data['edges']))
            self.assertEqual(sum(isinstance(n, NodeItem) for n in window.scene.items()), len(data['nodes']))
            clock = {'now': time.monotonic()}
            def advance_clock():
                clock['now'] += 100
                return clock['now']
            patches = [
                mock.patch('nodes.okww.time', new=SimpleNamespace(monotonic=advance_clock, time=time.time)),
                mock.patch('nodes.okww._relevant_processes', side_effect=inspect),
                mock.patch('nodes.system.execute_start_process', side_effect=launch),
                mock.patch('nodes.system.execute_sleep', return_value=True),
                mock.patch('nodes.okww.execute_sleep', return_value=True),
                mock.patch.object(window, '_confirm_execution_review', return_value=True),
                mock.patch('nodes.timers.execute_sleep', return_value=True),
                mock.patch('nodes.notifications.execute_reliable_bark_push', return_value={'delivered': True, 'queued': False}),
                mock.patch('functions.func_window.get_target_window', return_value=(99, (0, 0, 100, 100))),
                mock.patch('functions.func_vision.execute_template_match', return_value=((1, 1), 1.0) if scenario == 'update' else (None, 0.0)),
                mock.patch('nodes.okww.terminate_process_tree'),
            ]
            from contextlib import ExitStack
            try:
                with ExitStack() as stack:
                    for patch in patches:
                        stack.enter_context(patch)
                    hibernate = stack.enter_context(mock.patch('nodes.system.execute_delayed_hibernate', return_value=True))
                    exit_terminal = stack.enter_context(mock.patch('nodes.system.execute_self_destruct'))
                    window.compile_and_run_dag()
                    deadline = time.monotonic() + 10
                    while window.engine.is_running and time.monotonic() < deadline:
                        self.app.processEvents()
                        time.sleep(0.002)
                    self.assertFalse(window.engine.is_running, scenario)
                    self.assertFalse(window.engine.execution_failed, scenario)
                    if scenario in {'success', 'update_recovery', 'crash_recovery'}:
                        hibernate.assert_called_once_with(0)
                        exit_terminal.assert_called_once_with()
                        self.assertEqual(calls['launches'], 1 if scenario == 'success' else 2)
                        if scenario == 'update_recovery':
                            self.assertEqual(calls['paths'][-1], str(root / 'pythonw.exe'))
                            self.assertEqual(window.engine.global_context[okww.STATE_KEY]['attempt'], 1)
                    else:
                        hibernate.assert_not_called()
                        exit_terminal.assert_not_called()
                        self.assertEqual(calls['launches'], {'busy': 0, 'update': 1, 'exit': 3}[scenario])
                    records = recorder.path.read_text(encoding='utf-8')
                    self.assertIn('工作流执行完成', records)
                    self.assertIn('没有官方成功日志', records) if scenario == 'exit' else None
                    self.assertNotIn('api.day.app/', records)
            finally:
                stop_event.set()
                pool.waitForDone(3000)
                window.close()
                bus.node_status_changed.disconnect(window.engine._on_node_status_changed)
                bus.log_emitted.disconnect(window.append_log)
                bus.dag_completed.disconnect(window._on_dag_completed)
                bus.blueprint_jump_requested.disconnect(window.handle_blueprint_jump)
                recorder.close()
                stop_event.clear()

    def test_real_nodes_route_three_unconfirmed_exits_without_sleep(self):
        self.run_daily('exit')

    def test_real_nodes_confirm_success_before_power(self):
        self.run_daily('success')

    def test_real_nodes_confirm_localized_success_without_retry(self):
        self.run_daily('success', daily_completion='每日任务已完成')

    def test_real_nodes_preserve_busy_session_and_terminal(self):
        self.run_daily('busy')

    def test_real_visual_update_branch_never_sleeps(self):
        self.run_daily('update')

    def test_real_launcher_update_recovers_directly_then_completes(self):
        self.run_daily('update_recovery')

    def test_real_game_crash_cleans_and_retries_then_completes(self):
        self.run_daily('crash_recovery')


class SuccessEvidenceTests(unittest.TestCase):
    def test_generic_or_undated_success_cannot_authorize_daily(self):
        start = datetime.fromisoformat('2026-10-13 12:00:00').timestamp()
        for text in (SUCCESS_MARKER, f'2026-10-13 12:01:00 INFO {SUCCESS_MARKER}',
                     f'2026-10-12 12:01:00 INFO DailyTask:Daily Task Completed\n2026-10-13 12:01:00 INFO {SUCCESS_MARKER}'):
            self.assertIsNone(classify_log_update(text, not_before=start))

    def test_current_daily_completion_and_success_are_required(self):
        text = f'2026-10-13 12:01:00 INFO DailyTask:Daily Task Completed\n2026-10-13 12:01:00 INFO {SUCCESS_MARKER}'
        self.assertEqual(classify_log_update(text, not_before=datetime.fromisoformat('2026-10-13 12:00:00').timestamp())['state'], 'success')

    def test_v3719_chinese_completion_and_executor_exit_confirm_success(self):
        # Exact internal log shape observed after the ok-script 3.0.3 update.
        text = ('2026-11-05 19:20:21,117 INFO TaskExecutor DailyTask:每日任务已完成\n'
                f'2026-11-05 19:20:21,119 INFO TaskExecutor TaskExecutor:{SUCCESS_MARKER}\n')
        start = datetime.fromisoformat('2026-11-05 19:14:49').timestamp()
        self.assertEqual(classify_log_update(text, not_before=start)['state'], 'success')

    def test_localized_completion_still_requires_current_ordered_daily_evidence(self):
        start = datetime.fromisoformat('2026-11-05 19:00:00').timestamp()
        exit_line = f'2026-11-05 19:20:21,119 INFO TaskExecutor TaskExecutor:{SUCCESS_MARKER}\n'
        cases = (
            '2026-11-04 19:20:21,117 INFO TaskExecutor DailyTask:每日任务已完成\n' + exit_line,
            'INFO TaskExecutor DailyTask:每日任务已完成\n' + exit_line,
            exit_line + '2026-11-05 19:20:22,117 INFO TaskExecutor DailyTask:每日任务已完成\n',
            '2026-11-05 19:20:21,117 INFO TaskExecutor MultiAccountDailyTask:每日任务已完成\n' + exit_line,
            '2026-11-05 19:20:21,117 INFO TaskExecutor DailyTask:每日任务已完成\n',
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(classify_log_update(text, not_before=start))

    def test_log_redacts_notification_secret_and_survives_close(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = RunLog(directory)
            bus.log_emitted.emit('ERROR', 'test', 'failed https://api.day.app/secret/token')
            recorder.close()
            text = recorder.path.read_text(encoding='utf-8')
            self.assertIn('failed', text)
            self.assertNotIn('secret', text)


if __name__ == '__main__':
    unittest.main()
