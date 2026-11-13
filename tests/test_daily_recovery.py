"""Regression coverage for launcher-only hangs, game exits and frozen launches."""
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from functions import func_process
from functions.func_okww import launcher_update_state
from nodes import okww, system


class DailyRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.now = time.monotonic()
        self.state = {
            'attempt': 1, 'max_attempts': 3, 'attempt_started': self.now - 200,
            'attempt_wall_started': time.time() - 200,
            'workflow_started': self.now - 200, 'log_offsets': {},
            'saw_okww_process': False, 'missing_since': None,
            'settings': {'log_directory': 'outer', 'internal_log_directory': 'inner'},
        }
        self.context = {okww.STATE_KEY: self.state}
        self.logs = self.enterContext(mock.patch.object(okww, 'read_appended_logs', return_value=''))
        self.inventory = self.enterContext(mock.patch.object(okww, '_relevant_processes', return_value=[]))
        self.enterContext(mock.patch.object(okww, 'execute_sleep', return_value=True))
        self.enterContext(mock.patch.object(okww.time, 'monotonic', return_value=self.now))

    def monitor(self, **config):
        return okww.monitor_okww_task(config, {'__global_context__': self.context})

    def test_launcher_alone_cannot_satisfy_worker_startup(self):
        self.inventory.return_value = [{'pid': 1, 'role': 'okww_launcher'}]
        result = self.monitor()
        self.assertEqual(result['active_port'], '失败可重试')
        self.assertIn('未发现 OK-WW 工作进程', result['value']['summary'])

    def test_active_update_gets_longer_grace_and_no_visual_scan(self):
        stamp = datetime.now().isoformat(sep=' ', timespec='milliseconds')
        self.logs.side_effect = [f'{stamp} INFO Updating ok-ww to version v3.7.11\n', '']
        self.inventory.return_value = [{'pid': 1, 'role': 'okww_launcher'}]
        self.assertEqual(self.monitor()['active_port'], '运行中')
        self.state['attempt_started'] = self.now - 901
        self.logs.side_effect = None
        result = self.monitor()
        self.assertEqual(result['active_port'], '失败可重试')
        self.assertIn('更新超时', result['value']['summary'])

    def test_completed_update_waits_for_autostart_then_requests_direct_recovery(self):
        stamp = datetime.now().isoformat(sep=' ', timespec='milliseconds')
        self.logs.side_effect = [f'{stamp} INFO Auto Update to version v3.7.11 success.\n', '']
        self.assertEqual(self.monitor()['active_port'], '运行中')
        self.logs.side_effect = None
        self.state['launcher_update_finished_at'] = self.now - 91
        result = self.monitor()
        self.assertEqual(result['active_port'], '更新后重启')
        self.assertTrue(self.state['launch_worker_directly'])
        self.assertTrue(self.state['preserve_attempt_number'])
        self.assertEqual(self.state['attempt'], 1)

    def test_updated_gui_without_daily_activity_also_recovers(self):
        self.state.update(launcher_update_finished_at=self.now - 91,
                          launcher_update_phase='completed')
        self.inventory.return_value = [{'pid': 2, 'role': 'okww_worker'}]
        self.assertEqual(self.monitor()['active_port'], '更新后重启')

    def test_updated_worker_running_daily_is_not_restarted(self):
        self.state.update(launcher_update_finished_at=self.now - 91,
                          launcher_update_phase='completed')
        self.logs.return_value = 'INFO TaskExecutor DailyTask:info_set current task wait main'
        self.inventory.return_value = [{'pid': 2, 'role': 'okww_worker'}]
        self.assertEqual(self.monitor()['active_port'], '运行中')
        self.assertNotIn('launch_worker_directly', self.state)
        self.inventory.return_value = []
        self.state['missing_since'] = self.now - 21
        self.assertEqual(self.monitor()['active_port'], '失败可重试')

    def test_repeated_update_recovery_stops_at_limit(self):
        self.state.update(launcher_update_finished_at=self.now - 91,
                          update_restart_count=3, max_update_restarts=3)
        self.assertEqual(self.monitor()['active_port'], '最终失败')

    def test_game_exit_with_living_worker_gets_grace_then_retry(self):
        self.state['saw_game_process'] = True
        self.inventory.return_value = [{'pid': 2, 'role': 'okww_worker'}]
        self.assertEqual(self.monitor()['active_port'], '运行中')
        self.state['game_missing_since'] = self.now - 61
        result = self.monitor()
        self.assertEqual(result['active_port'], '失败可重试')
        self.assertIn('疑似崩溃', result['value']['summary'])

    def test_game_returning_during_grace_cancels_crash_recovery(self):
        self.state.update(saw_game_process=True, game_missing_since=self.now - 61)
        self.inventory.return_value = [{'pid': 2, 'role': 'okww_worker'}, {'pid': 3, 'role': 'game'}]
        self.assertEqual(self.monitor()['active_port'], '运行中')
        self.assertIsNone(self.state['game_missing_since'])

    def test_launch_failure_routes_through_retry_cleanup(self):
        self.state['launch_error'] = 'OK-WW 程序启动失败'
        self.assertEqual(self.monitor()['active_port'], '失败可重试')
        self.inventory.assert_not_called()


class ExternalLaunchTests(unittest.TestCase):
    def test_update_transition_ignores_stale_and_snapshot_lines(self):
        start = datetime.fromisoformat('2026-10-25 19:00:00').timestamp()
        text = ('2026-10-24 19:00:00 INFO Auto Update to version v3.7.9 success.\n'
                '2026-10-25 19:00:01 INFO app update_state: Idle, running: true\n')
        self.assertIsNone(launcher_update_state(text, start))
        text += '2026-10-25 19:00:02 INFO Updating ok-ww to version v3.7.11\n'
        self.assertEqual(launcher_update_state(text, start), 'updating')
        text += '2026-10-25 19:00:03 INFO Auto Update to version v3.7.11 success.\n'
        self.assertEqual(launcher_update_state(text, start), 'completed')

    def test_direct_recovery_preserves_task_args_and_script_working_directory(self):
        with tempfile.TemporaryDirectory(prefix='daily recovery ') as temp:
            script = Path(temp) / 'working' / 'main.py'
            script.parent.mkdir()
            script.touch()
            python = str(Path(temp) / 'python' / 'pythonw.exe')
            context = {okww.STATE_KEY: {'launch_worker_directly': True, 'settings': {
                'okww_main_script': str(script), 'okww_worker_executable': python}}}
            with mock.patch.object(system, 'execute_start_process', return_value=(True, 123)) as launch, \
                    mock.patch.object(system, 'execute_sleep', return_value=True):
                result = system.start_program({'程序路径': 'ok-ww.exe', '启动参数': '-t 1 -e',
                                               'OK-WW更新后恢复启动': '是'},
                                              {'__global_context__': context})
            self.assertEqual(result['pid'], 123)
            launch.assert_called_once_with(python, subprocess.list2cmdline([str(script)]) + ' -t 1 -e',
                                           working_dir=str(script.parent), launch_if_running=False)

    def test_same_name_in_another_python_installation_is_not_a_duplicate(self):
        inventory = [{'pid': 12, 'name': 'pythonw.exe', 'executable_path': r'C:\other\pythonw.exe'},
                     {'pid': 34, 'name': 'pythonw.exe', 'executable_path': r'C:\ok-ww\pythonw.exe'}]
        with mock.patch('functions.func_okww.windows_process_inventory', return_value=inventory):
            self.assertEqual(func_process._find_running_process_pid(r'C:\ok-ww\pythonw.exe'), 34)

    def test_child_env_removes_bundle_paths_without_mutating_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle = str(Path(temp) / '_internal')
            normal = str(Path(temp) / 'normal')
            values = {'PATH': os.pathsep.join([bundle, bundle + os.sep + 'Qt', normal]),
                      'PYTHONHOME': 'bad', 'PYTHONPATH': 'bad', 'QT_PLUGIN_PATH': 'bad'}
            with mock.patch.dict(os.environ, values), mock.patch.object(sys, '_MEIPASS', bundle, create=True):
                env = func_process.external_process_environment()
                self.assertEqual(env['PATH'], normal)
                self.assertNotIn('PYTHONHOME', env)
                self.assertNotIn('QT_PLUGIN_PATH', env)
                self.assertEqual(os.environ['PYTHONHOME'], 'bad')

    @unittest.skipUnless(os.name == 'nt', 'Windows external launch')
    def test_real_child_receives_clean_dll_search_env_cwd_and_arguments(self):
        with tempfile.TemporaryDirectory(prefix='external launch ') as temp:
            script = Path(temp) / 'probe.py'
            output = Path(temp) / 'result.json'
            script.write_text(
                'import ctypes,json,os,sys\n'
                'v=ctypes.create_unicode_buffer(32768)\n'
                'ctypes.windll.kernel32.GetDllDirectoryW(len(v),v)\n'
                'json.dump(dict(pid=os.getpid(),dll=v.value,cwd=os.getcwd(),args=sys.argv[2:],'
                'pythonpath=os.environ.get("PYTHONPATH")),open(sys.argv[1],"w"))\n', encoding='utf-8')
            children = []
            real_popen = subprocess.Popen

            def spawn(*args, **kwargs):
                child = real_popen(*args, **kwargs)
                children.append(child)
                return child

            try:
                with mock.patch.object(func_process, '_find_running_process_pid', return_value=None), \
                        mock.patch.object(sys, 'frozen', True, create=True), \
                        mock.patch.dict(os.environ, {'PYTHONPATH': temp}), \
                        mock.patch.object(func_process.subprocess, 'Popen', side_effect=spawn):
                    success, pid = func_process.execute_start_process(
                        # The Windows venv redirector can launch a second process;
                        # use the actual interpreter to test the returned PID.
                        getattr(sys, '_base_executable', sys.executable),
                        subprocess.list2cmdline([str(script), str(output), 'a b', '-t', '1', '-e']),
                        working_dir=temp)
                self.assertTrue(success)
                self.assertEqual(len(children), 1)
                # File creation precedes process exit; Windows keeps its cwd locked.
                self.assertEqual(children[0].wait(timeout=5), 0)
                result = json.loads(output.read_text())
                self.assertEqual(result['pid'], pid)
                self.assertEqual(result['dll'], '')
                self.assertEqual(result['cwd'], temp)
                self.assertEqual(result['args'], ['a b', '-t', '1', '-e'])
                self.assertIsNone(result['pythonpath'])
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                    child.wait(timeout=5)

    @unittest.skipUnless(os.name == 'nt', 'Windows DLL search inheritance')
    def test_real_windows_dll_search_is_reset_and_restored_even_on_error(self):
        kernel32 = ctypes.WinDLL('kernel32')
        get_directory = kernel32.GetDllDirectoryW
        get_directory.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p]
        set_directory = kernel32.SetDllDirectoryW
        set_directory.argtypes = [ctypes.c_wchar_p]
        def read():
            value = ctypes.create_unicode_buffer(32768)
            get_directory(len(value), value)
            return value.value
        original = read()
        try:
            with tempfile.TemporaryDirectory() as bundle:
                set_directory(bundle)
                with mock.patch.object(sys, 'frozen', True, create=True):
                    with self.assertRaisesRegex(RuntimeError, 'spawn failed'):
                        with func_process.external_dll_search():
                            self.assertEqual(read(), '')
                            raise RuntimeError('spawn failed')
                self.assertEqual(read(), bundle)
        finally:
            set_directory(original or None)


if __name__ == '__main__':
    unittest.main()
