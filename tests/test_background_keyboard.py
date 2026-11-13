import json
import unittest
from pathlib import Path
from unittest.mock import call, patch

import win32con

from nodes import keyboard_backend
from nodes.actions import dynamic_paste_action, keyboard_action
from nodes.triggers import check_program_status


class PostMessageKeyboardTests(unittest.TestCase):
    def test_ok_ww_style_key_messages_include_scan_code_lparam(self):
        with patch.object(keyboard_backend.stop_event, "is_set", return_value=False), patch.object(
            keyboard_backend.stop_event, "wait", return_value=False
        ), patch(
            "nodes.keyboard_backend.win32gui.IsWindow", return_value=True
        ), patch(
            "nodes.keyboard_backend.win32gui.GetAncestor", return_value=321
        ), patch(
            "nodes.keyboard_backend.win32api.MapVirtualKey", return_value=0x11
        ), patch(
            "nodes.keyboard_backend.win32gui.PostMessage"
        ) as post_message:
            success = keyboard_backend.execute_post_message_key_spec(
                321, "W", duration=1.5, name="WalkTest"
            )

        self.assertTrue(success)
        self.assertEqual(
            post_message.call_args_list,
            [
                call(321, win32con.WM_ACTIVATE, win32con.WA_ACTIVE, 0),
                call(321, win32con.WM_KEYDOWN, ord("W"), 0x00110001),
                call(321, win32con.WM_KEYUP, ord("W"), 0xC0110001),
            ],
        )

    def test_background_text_posts_every_character_exactly_once(self):
        with patch.object(keyboard_backend.stop_event, "is_set", return_value=False), patch.object(
            keyboard_backend.stop_event, "wait", return_value=False
        ), patch(
            "nodes.keyboard_backend.win32gui.IsWindow", return_value=True
        ), patch(
            "nodes.keyboard_backend.win32gui.GetAncestor", return_value=321
        ), patch(
            "nodes.keyboard_backend.win32gui.PostMessage"
        ) as post_message:
            success = keyboard_backend.execute_post_message_text(
                321, "MOEALKYNE", interval=0, name="CodeTest"
            )

        self.assertTrue(success)
        expected = [call(321, win32con.WM_ACTIVATE, win32con.WA_ACTIVE, 0)]
        expected.extend(
            call(321, win32con.WM_CHAR, ord(char), 1) for char in "MOEALKYNE"
        )
        self.assertEqual(post_message.call_args_list, expected)

    def test_keyboard_node_can_find_window_and_use_post_message(self):
        with patch("nodes.actions.time.sleep"), patch(
            "functions.func_window.get_target_window",
            return_value=(456, (0, 0, 1920, 1080)),
        ), patch(
            "nodes.actions.execute_post_message_key_spec", return_value=True
        ) as execute:
            result = keyboard_action(
                {
                    "操作类型": "敲击单键",
                    "输入方式": "后台消息(PostMessage)",
                    "目标窗口标题(后台消息)": "鸣潮",
                    "按键名(如 F/SPACE/ENTER) 或 文本": "esc",
                    "按压时长(s)": "0.05",
                    "操作前延迟(s)": "0",
                },
                {},
            )

        execute.assert_called_once_with(456, "ESC", 0.05, "DAG_ESC")
        self.assertEqual(result["hwnd"], 456)

    def test_dynamic_paste_writes_each_background_character_once(self):
        with patch("nodes.actions.time.sleep"), patch(
            "nodes.actions.execute_post_message_text", return_value=True
        ) as execute:
            result = dynamic_paste_action(
                {
                    "输入方式": "后台消息(PostMessage)",
                    "读取变量名": "current_cdkey",
                    "操作前延迟(s)": "0",
                },
                {"hwnd": 789, "__value__": "TESTCODE123"},
            )

        execute.assert_called_once_with(
            789,
            "TESTCODE123",
            0.02,
            "DAG_DynamicPaste_current_cdkey",
        )
        self.assertEqual(result["value"], "TESTCODE123")

    def test_window_status_forwards_detected_hwnd(self):
        with patch(
            "nodes.triggers.get_target_window",
            return_value=(987, (0, 0, 1920, 1080)),
        ):
            result = check_program_status(
                {"检测模式": "按窗口标题", "目标名称": "鸣潮"}, {}
            )

        self.assertEqual(result["active_port"], "已运行")
        self.assertEqual(result["hwnd"], 987)
        self.assertEqual(result["value"], {"running": True, "hwnd": 987})


class BackgroundWorkflowTests(unittest.TestCase):
    def test_redeem_workflow_uses_background_vision_and_keyboard(self):
        workflow = json.loads((Path(__file__).resolve().parent / "fixtures" / "1.json").read_text(encoding="utf-8"))
        vision_nodes = [node for node in workflow["nodes"] if node["type"] == "视觉寻图"]
        keyboard_nodes = [node for node in workflow["nodes"] if node["type"] == "键盘操作"]
        paste_node = next(node for node in workflow["nodes"] if node["id"] == "paste-code")

        self.assertEqual(len(vision_nodes), 8)
        self.assertTrue(
            all(node["config"]["执行模式"] == "后台(静默寻图)" for node in vision_nodes)
        )
        self.assertTrue(
            all(
                node["config"]["输入方式"] == "后台消息(PostMessage)"
                for node in keyboard_nodes
            )
        )
        self.assertEqual(paste_node["config"]["输入方式"], "后台消息(PostMessage)")

    def test_minimal_game_keyboard_workflow_only_tests_w_and_esc(self):
        workflow = json.loads(
            (Path(__file__).resolve().parent / "fixtures" / "鸣潮_后台键盘测试.json").read_text(encoding="utf-8")
        )
        node_types = [node["type"] for node in workflow["nodes"]]
        keyboard_nodes = [node for node in workflow["nodes"] if node["type"] == "键盘操作"]
        key_specs = [
            node["config"]["按键名(如 F/SPACE/ENTER) 或 文本"]
            for node in keyboard_nodes
        ]

        self.assertEqual(node_types.count("状态检测"), 1)
        self.assertEqual(key_specs, ["W", "ESC", "ESC"])
        self.assertNotIn("启动程序", node_types)
        self.assertNotIn("通用网页嗅探", node_types)
        self.assertTrue(
            all(
                node["config"]["输入方式"] == "后台消息(PostMessage)"
                for node in keyboard_nodes
            )
        )


if __name__ == "__main__":
    unittest.main()
