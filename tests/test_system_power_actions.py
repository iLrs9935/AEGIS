import unittest
from unittest import mock

from nodes import system


class SystemPowerActionTests(unittest.TestCase):
    def setUp(self):
        self.hibernate = self.enterContext(
            mock.patch.object(system, "execute_delayed_hibernate", return_value=True)
        )
        self.exit_terminal = self.enterContext(
            mock.patch.object(system, "execute_self_destruct")
        )
        self.sleep = self.enterContext(
            mock.patch.object(system, "execute_sleep", return_value=True)
        )

    def test_exit_only_never_schedules_hibernation(self):
        result = system.s4_hibernate_and_exit(
            {"执行动作": "仅退出终端(不休眠)", "执行前倒计时(s)": "5"}, {}
        )
        self.assertEqual(result["status"], "Success")
        self.hibernate.assert_not_called()
        self.exit_terminal.assert_called_once_with()

    def test_explicit_hibernation_schedules_configured_delay_then_exits(self):
        calls = mock.Mock()
        calls.attach_mock(self.hibernate, "hibernate")
        calls.attach_mock(self.exit_terminal, "exit_terminal")
        result = system.s4_hibernate_and_exit(
            {"执行动作": "S4休眠并退出终端", "执行前倒计时(s)": "12"}, {}
        )
        self.assertEqual(result["status"], "Success")
        self.assertEqual(
            calls.mock_calls, [mock.call.hibernate(0), mock.call.exit_terminal()]
        )

    def test_unknown_action_has_no_power_or_exit_effect(self):
        for action in ("不休眠", "休眠", "", None, ["S4休眠并退出终端"]):
            with self.subTest(action=action):
                result = system.s4_hibernate_and_exit({"执行动作": action}, {})
                self.assertEqual(result["status"], "Error")
        self.hibernate.assert_not_called()
        self.exit_terminal.assert_not_called()
        self.sleep.assert_not_called()

    def test_invalid_hibernation_delay_has_no_power_or_exit_effect(self):
        for delay in ("invalid", "-1", None):
            with self.subTest(delay=delay):
                result = system.s4_hibernate_and_exit(
                    {"执行动作": "S4休眠并退出终端", "执行前倒计时(s)": delay}, {}
                )
                self.assertEqual(result["status"], "Error")
        self.hibernate.assert_not_called()
        self.exit_terminal.assert_not_called()

    def test_failed_hibernation_schedule_keeps_terminal_open(self):
        self.hibernate.return_value = False
        result = system.s4_hibernate_and_exit(
            {"执行动作": "S4休眠并退出终端", "执行前倒计时(s)": "5"}, {}
        )
        self.assertEqual(result["status"], "Error")
        self.hibernate.assert_called_once_with(0)
        self.exit_terminal.assert_not_called()

    def test_preserve_terminal_neither_sleeps_nor_exits(self):
        result = system.s4_hibernate_and_exit({'执行动作': '保留终端(不休眠)'}, {})
        self.assertEqual(result['status'], 'Success')
        self.hibernate.assert_not_called()
        self.exit_terminal.assert_not_called()

    def test_stop_during_countdown_never_schedules_power(self):
        self.sleep.side_effect = [True, False]
        result = system.s4_hibernate_and_exit({'执行动作': 'S4休眠并退出终端'}, {})
        self.assertEqual(result['status'], 'Cancelled')
        self.hibernate.assert_not_called()
        self.exit_terminal.assert_not_called()

    def test_missing_or_failure_proof_blocks_even_spoofed_success_input(self):
        from nodes.okww import STATE_KEY
        for state in (None, {}, {'terminal_state': 'final_failure', 'cleanup_verified': True},
                      {'terminal_state': 'success', 'cleanup_verified': False}):
            context = {} if state is None else {STATE_KEY: state}
            result = system.s4_hibernate_and_exit(
                {'执行动作': 'S4休眠并退出终端', '休眠前校验': '本次OK-WW成功且清理完成'},
                {'__global_context__': context, '__value__': {'state': 'success', 'cleanup': 'verified'}})
            self.assertEqual(result['status'], 'Error')
        self.hibernate.assert_not_called()
        self.exit_terminal.assert_not_called()

    def test_new_process_during_countdown_revokes_permission(self):
        from nodes.okww import STATE_KEY
        with mock.patch('nodes.okww._relevant_processes', side_effect=[[], [{'pid': 1}]]):
            result = system.s4_hibernate_and_exit(
                {'执行动作': 'S4休眠并退出终端', '执行前倒计时(s)': '1'},
                {'__global_context__': {STATE_KEY: {'terminal_state': 'success', 'cleanup_verified': True, 'settings': {}}}})
        self.assertEqual(result['status'], 'Error')
        self.hibernate.assert_not_called()


class PowerHALTests(unittest.TestCase):
    def test_cancelled_delay_does_not_spawn_detached_command(self):
        from functions import func_system
        with mock.patch.object(func_system, 'execute_sleep', return_value=False), mock.patch.object(func_system.subprocess, 'run') as run:
            self.assertFalse(func_system.execute_delayed_hibernate(10))
            run.assert_not_called()

    def test_safe_mode_never_executes_shutdown_or_exit(self):
        from functions import func_system
        with mock.patch.object(func_system, 'SAFE_POWER_MODE', True), mock.patch.object(func_system.subprocess, 'run') as run, mock.patch.object(func_system.os, '_exit') as exit_process:
            self.assertTrue(func_system.execute_delayed_hibernate(0))
            func_system.execute_self_destruct()
            run.assert_not_called()
            exit_process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
