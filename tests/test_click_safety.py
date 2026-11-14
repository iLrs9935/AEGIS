"""Unit tests: every native mouse interface is mocked, including cursor moves."""
from contextlib import ExitStack
from copy import deepcopy
import unittest
from unittest.mock import patch

from core.workflow import migrate_click_modes
from nodes.actions import click_target, rapid_click_target


class ClickSafetyTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.cursor = self.stack.enter_context(patch("nodes.actions.win32api.SetCursorPos"))
        self.click = self.stack.enter_context(patch("nodes.actions.execute_global_mouse_action", return_value=True))
        self.background = self.stack.enter_context(patch("nodes.actions.execute_background_click", return_value=True))
        self.rapid = self.stack.enter_context(patch("nodes.actions.execute_rapid_click", return_value=True))
        self.stack.enter_context(patch("nodes.actions.win32api.GetSystemMetrics", side_effect=lambda i: {76: -100, 77: 0, 78: 2020, 79: 1080}[i]))
        self.stack.enter_context(patch("nodes.actions.win32gui.IsWindow", return_value=True))
        self.stack.enter_context(patch("nodes.actions.time.sleep"))

    def assert_no_effects(self):
        for operation in (self.cursor, self.click, self.background, self.rapid):
            operation.assert_not_called()

    def test_valid_coordinate_click_and_rapid_click(self):
        for func in (click_target, rapid_click_target):
            result = func({"坐标模式": "指定坐标"}, {"target_x": -50, "target_y": 100})
            self.assertEqual(result["status"], "Success")
        self.assertEqual(self.cursor.call_count, 2)
        self.click.assert_called_once()
        self.rapid.assert_called_once_with("left", 20, 0.05, "DAG_RapidClick")

    def test_missing_x_or_y_and_invalid_types_never_move_or_click(self):
        for point in ({}, {"target_x": 10}, {"target_y": 20},
                      {"target_x": "10", "target_y": 20},
                      {"target_x": True, "target_y": 20},
                      {"target_x": [], "target_y": 20},
                      {"target_x": 10.5, "target_y": 20},
                      {"target_x": float("nan"), "target_y": 20},
                      {"target_x": 10, "target_y": float("inf")}):
            for func in (click_target, rapid_click_target):
                with self.subTest(point=point, func=func.__name__):
                    result = func({"坐标模式": "指定坐标"}, point)
                    self.assertEqual(result["status"], "Failed")
                    self.assertTrue(result["error"])
                    self.assert_no_effects()

    def test_virtual_desktop_bounds_reject_outside_and_accept_edge(self):
        for x, y in ((-101, 0), (1920, 0), (0, -1), (0, 1080)):
            for func in (click_target, rapid_click_target):
                self.assertEqual(func({"坐标模式": "指定坐标"}, {"target_x": x, "target_y": y})["status"], "Failed")
        self.assert_no_effects()
        self.assertEqual(click_target({"坐标模式": "指定坐标"}, {"target_x": 1919, "target_y": 1079})["status"], "Success")

    def test_current_position_requires_explicit_mode(self):
        for func in (click_target, rapid_click_target):
            self.assertEqual(func({}, {"target_x": 10, "target_y": 20})["status"], "Failed")
            self.assertEqual(func({"坐标模式": "automatic"}, {})["status"], "Failed")
        self.assert_no_effects()
        for func in (click_target, rapid_click_target):
            self.assertEqual(func({"坐标模式": "当前位置"}, {})["status"], "Success")
        self.cursor.assert_not_called()
        self.click.assert_called_once()
        self.rapid.assert_called_once()

    def test_background_click_needs_coordinates_and_valid_window(self):
        config = {"坐标模式": "当前位置", "执行模式": "后台静默(不抢鼠标)"}
        self.assertEqual(click_target(config, {"hwnd": 99})["status"], "Failed")
        config["坐标模式"] = "指定坐标"
        point = {"target_x": 10, "target_y": 20}
        self.assertEqual(click_target(config, point)["status"], "Failed")
        self.assert_no_effects()
        self.assertEqual(click_target(config, {**point, "hwnd": 99})["status"], "Success")
        self.background.assert_called_once_with(99, 10, 20, "left", "单击", "DAG_left")
        self.cursor.assert_not_called()

    def test_invalid_count_interval_button_and_delay_fail_before_effects(self):
        invalid = [{"点击次数": value} for value in (None, True, "bad", 0, -1, 1.5, 10001, float("inf"))]
        invalid += [{"点击间隔(s)": value} for value in (-1, "nan", None, True, "bad")]
        invalid += [{"点击按键": "anything"}]
        for config in invalid:
            with self.subTest(config=config):
                self.assertEqual(rapid_click_target({"坐标模式": "当前位置", **config}, {})["status"], "Failed")
        for delay in (-1, "nan", None, True):
            self.assertEqual(click_target({"坐标模式": "当前位置", "操作前延迟(s)": delay}, {})["status"], "Failed")
        self.assert_no_effects()

    def test_backend_failure_is_reported_and_subsequent_call_recovers(self):
        self.rapid.side_effect = [False, True]
        self.assertEqual(rapid_click_target({"坐标模式": "当前位置"}, {})["status"], "Failed")
        self.assertEqual(rapid_click_target({"坐标模式": "当前位置"}, {})["status"], "Success")

    def test_legacy_migration_is_explicit_idempotent_and_never_grants_current_position(self):
        old = {"nodes": [{"id": "old", "type": "连续物理点击", "config": {}}], "edges": []}
        original = deepcopy(old)
        migrated, notices = migrate_click_modes(old)
        self.assertEqual(old, original)
        self.assertTrue(notices)
        self.assertEqual(migrated["nodes"][0]["config"]["坐标模式"], "指定坐标")
        self.assertTrue(migrated["meta"]["click_migration_required_review"])
        self.assertEqual(rapid_click_target(migrated["nodes"][0]["config"], {})["status"], "Failed")
        self.assert_no_effects()
        second, notices = migrate_click_modes(migrated)
        self.assertEqual(second, migrated)
        self.assertEqual(notices, [])
