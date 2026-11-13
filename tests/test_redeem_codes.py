import unittest
import re
import json
from pathlib import Path
from unittest.mock import Mock, patch, sentinel

from functions import func_crawler
from functions import func_process, func_vision
from core.engine import DAGEngine
from nodes.actions import dynamic_paste_action, mouse_wheel_action
from nodes.logic import logic_iterator_node
from nodes.network import fetch_web_data, record_redeem_result
from nodes.vision import find_target_image


class FakeVault:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def read(self, key):
        return self.values.get(key)

    def write(self, key, value):
        self.values[key] = value
        return True


class RedeemLedgerTests(unittest.TestCase):
    def setUp(self):
        self.original_vault = func_crawler.vault
        self.vault = FakeVault()
        func_crawler.vault = self.vault

    def tearDown(self):
        func_crawler.vault = self.original_vault

    def test_discovered_code_stays_pending_until_confirmed(self):
        self.vault.values["mingchao_cdkeys"] = {
            "discovered": {"FIRSTCODE123": {}, "SECONDCODE12": {}},
            "processed": {"FIRSTCODE123": {"result": "兑换成功"}},
            "seen_posts": [],
        }

        ledger = func_crawler.load_cdkey_ledger("mingchao_cdkeys")
        self.assertEqual(func_crawler.pending_cdkeys(ledger), ["SECONDCODE12"])

        func_crawler.mark_cdkey_processed(
            "secondcode12", result="兑换成功", ledger_key="mingchao_cdkeys"
        )
        ledger = func_crawler.load_cdkey_ledger("mingchao_cdkeys")
        self.assertEqual(func_crawler.pending_cdkeys(ledger), [])
        self.assertEqual(
            ledger["processed"]["SECONDCODE12"]["result"], "兑换成功"
        )

    def test_legacy_discovery_is_not_mistaken_for_success(self):
        self.vault.values["aegis_seen_cdkeys"] = ["LEGACYCODE12"]
        ledger = func_crawler.load_cdkey_ledger("mingchao_cdkeys")
        self.assertEqual(func_crawler.pending_cdkeys(ledger), ["LEGACYCODE12"])

    def test_user_prefixed_page_ids_are_removed_from_existing_ledger(self):
        self.vault.values["mingchao_cdkeys"] = {
            "discovered": {"USER702609644": {}, "REALCODE123": {}},
            "processed": {"USER123737058": {"result": "legacy"}},
            "seen_posts": [],
        }
        ledger = func_crawler.load_cdkey_ledger("mingchao_cdkeys")
        self.assertEqual(func_crawler.pending_cdkeys(ledger), ["REALCODE123"])
        self.assertNotIn("USER702609644", ledger["discovered"])
        self.assertNotIn("USER123737058", ledger["processed"])

    def test_result_node_commits_current_context_code(self):
        result = record_redeem_result(
            {
                "记忆账本键名": "mingchao_cdkeys",
                "当前兑换码兼容变量": "current_cdkey",
                "处理结果": "已使用/已失效",
            },
            {
                "__value__": True,
                "__global_context__": {"current_cdkey": "DONECODE1234"},
            },
        )
        self.assertEqual(result["value"], "DONECODE1234")
        ledger = func_crawler.load_cdkey_ledger("mingchao_cdkeys")
        self.assertEqual(
            ledger["processed"]["DONECODE1234"]["result"], "已使用/已失效"
        )


class RedeemFlowTests(unittest.TestCase):
    def test_engine_rejects_overlapping_execution(self):
        engine = DAGEngine()
        engine.is_running = True
        self.assertFalse(engine.start_execution())

    def test_blueprint_jump_status_releases_active_node(self):
        engine = DAGEngine()
        engine.is_running = True
        engine.active_nodes = {"jump-node"}

        with patch.object(engine, "_schedule_finish_check") as finish_check:
            engine._on_node_status_changed(
                "jump-node", "Jump_Triggered", "{'status': 'Jump_Triggered'}"
            )

        self.assertEqual(engine.active_nodes, set())
        self.assertTrue(engine.execution_failed)
        finish_check.assert_called_once_with()

    def test_process_launcher_skips_an_existing_instance(self):
        with patch("functions.func_process.os.path.exists", return_value=True), patch(
            "functions.func_process._find_running_process_pid", return_value=2468
        ), patch("functions.func_process.subprocess.Popen") as popen:
            success, pid = func_process.execute_start_process(
                r"D:\\Games\\Wuthering Waves.exe"
            )
        self.assertTrue(success)
        self.assertEqual(pid, 2468)
        popen.assert_not_called()

    def test_process_launcher_can_reinvoke_existing_app_to_wake_its_window(self):
        fake_process = Mock(pid=9753)
        with patch("functions.func_process.os.path.exists", return_value=True), patch(
            "functions.func_process._find_running_process_pid", return_value=2468
        ), patch(
            "functions.func_process.subprocess.Popen", return_value=fake_process
        ) as popen:
            success, pid = func_process.execute_start_process(
                r"C:\\Apps\\SDKDNS.exe", launch_if_running=True
            )
        self.assertTrue(success)
        self.assertEqual(pid, 9753)
        popen.assert_called_once()

    def test_vision_retry_obeys_emergency_stop(self):
        func_vision.stop_event.set()
        try:
            with patch("functions.func_vision.pyautogui.size", return_value=(3840, 2160)):
                pos, confidence = func_vision.execute_template_match(
                    hwnd=100,
                    rect=(-16, -72, 3856, 2176),
                    pic_path="images/cdkey_process/1.png",
                    retry_count=20,
                    retry_interval=3.0,
                )
        finally:
            func_vision.stop_event.clear()
        self.assertIsNone(pos)
        self.assertEqual(confidence, 0.0)

    def test_vision_clips_4k_border_and_matches_150_percent_template(self):
        template = func_vision.cv2.imdecode(
            func_vision.np.fromfile(
                "images/cdkey_process/1.png", dtype=func_vision.np.uint8
            ),
            func_vision.cv2.IMREAD_GRAYSCALE,
        )
        scaled = func_vision.cv2.resize(template, None, fx=1.5, fy=1.5)
        canvas = func_vision.np.zeros((600, 800), dtype=func_vision.np.uint8)
        y, x = 180, 100
        height, width = scaled.shape
        canvas[y : y + height, x : x + width] = scaled
        screenshot = func_vision.PILImage.fromarray(
            func_vision.cv2.cvtColor(canvas, func_vision.cv2.COLOR_GRAY2RGB)
        )

        with patch("functions.func_vision.pyautogui.size", return_value=(800, 600)), patch(
            "functions.func_vision.pyautogui.screenshot", return_value=screenshot
        ) as capture, patch(
            "functions.func_vision.force_activate_window", return_value=True
        ), patch(
            "functions.func_vision.win32gui.IsWindow", return_value=True
        ):
            pos, confidence = func_vision.execute_template_match(
                hwnd=100,
                rect=(-16, -72, 816, 672),
                pic_path="images/cdkey_process/1.png",
                confidence=0.72,
                retry_count=1,
                retry_interval=0,
            )

        capture.assert_called_once_with(region=(0, 0, 800, 600))
        self.assertGreaterEqual(confidence, 0.99)
        self.assertEqual(pos, (x + width // 2, y + height // 2))

    def test_complete_workflow_keeps_every_visual_step_decoupled(self):
        workflow = json.loads(
            (Path(__file__).resolve().parent / "fixtures" / "1.json").read_text(encoding="utf-8")
        )
        node_types = [node["type"] for node in workflow["nodes"]]
        edges = {
            (edge["src_id"], edge["src_port"], edge["tgt_id"])
            for edge in workflow["edges"]
        }

        self.assertEqual(node_types.count("视觉寻图"), 8)
        self.assertEqual(node_types.count("信号分流器"), 8)
        self.assertEqual(node_types.count("物理点击"), 8)
        self.assertNotIn("视觉点击", node_types)
        self.assertEqual(node_types.count("持续滚轮"), 1)
        for index in range(1, 8):
            self.assertIn((f"vision-{index}", "OUT", f"router-{index}"), edges)
            self.assertIn(
                (f"router-{index}", "找到目标", f"click-{index}"), edges
            )

        nodes_by_id = {node["id"]: node for node in workflow["nodes"]}
        self.assertEqual(
            nodes_by_id["vision-6"]["config"]["图片路径"],
            "images/cdkey_process/6.1.png",
        )
        self.assertEqual(
            nodes_by_id["vision-cancel"]["config"]["图片路径"],
            "images/cdkey_process/7.1.png",
        )
        self.assertEqual(
            nodes_by_id["wait-submit"]["config"]["等待时长(s)"], "3"
        )
        self.assertEqual(
            nodes_by_id["record-code"]["config"]["处理结果"], "已使用"
        )
        self.assertNotIn("vision-error", nodes_by_id)
        self.assertNotIn("router-error", nodes_by_id)
        self.assertNotIn("record-invalid", nodes_by_id)
        self.assertIn(("wait-submit", "OUT", "vision-cancel"), edges)
        self.assertIn(("vision-cancel", "OUT", "router-cancel"), edges)
        self.assertIn(("router-cancel", "找到取消", "click-cancel"), edges)
        self.assertIn(("click-cancel", "OUT", "record-code"), edges)
        self.assertIn(("record-code", "继续下一个", "code-iterator"), edges)

    def test_vision_resolves_relative_asset_from_project_root(self):
        with patch(
            "functions.func_window.get_target_window",
            return_value=(100, (0, 0, 1920, 1080)),
        ), patch(
            "functions.func_vision.execute_template_match",
            return_value=((50, 60), 0.95),
        ) as match:
            result = find_target_image(
                {
                    "窗口标题": "鸣潮",
                    "图片路径": "images/cdkey_process/1.png",
                    "置信度": "0.7",
                    "灰度匹配": "是",
                    "执行模式": "前台(拉起窗口)",
                    "匹配策略": "最高置信度",
                    "目标序号(第几个)": "1",
                    "重试次数": "1",
                    "重试间隔(s)": "0",
                },
                {},
            )
        self.assertTrue(result["value"]["found"])
        self.assertTrue(match.call_args.kwargs["pic_path"].endswith(
            "images\\cdkey_process\\1.png"
        ))

    def test_mouse_wheel_node_uses_configured_duration(self):
        with patch("nodes.actions.time.sleep"), patch(
            "nodes.actions.execute_mouse_wheel", return_value=True
        ) as execute:
            result = mouse_wheel_action(
                {
                    "滚动方向": "向下",
                    "持续时长(s)": "5",
                    "操作前延迟(s)": "0",
                },
                {"__value__": "keep"},
            )
        execute.assert_called_once_with("向下", 5.0, "DAG_MouseWheel")
        self.assertEqual(result["value"], "keep")

    def test_default_pattern_catches_short_codes_but_rejects_numeric_ids(self):
        pattern = re.compile(
            r"\b(?!USER)(?=[A-Z0-9]{8,20}\b)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{8,20}\b"
        )
        text = (
            "PAPERPLANE WARMSUNLIGHT JOURNEYWELL "
            "USER702609644 USER123737058 author 455638126"
        )
        self.assertEqual(
            pattern.findall(text),
            ["PAPERPLANE", "WARMSUNLIGHT", "JOURNEYWELL"],
        )

    def test_chrome_driver_uses_mirror_before_selenium_manager(self):
        with patch.object(
            func_crawler.ChinaChromeDriverManager,
            "install",
            return_value=r"C:\\drivers\\chromedriver.exe",
        ) as install, patch(
            "functions.func_crawler.webdriver.Chrome",
            return_value=sentinel.driver,
        ) as chrome:
            driver = func_crawler._create_chrome_driver(sentinel.options)

        self.assertIs(driver, sentinel.driver)
        install.assert_called_once_with()
        self.assertEqual(chrome.call_count, 1)
        self.assertIn("service", chrome.call_args.kwargs)
        self.assertIs(chrome.call_args.kwargs["options"], sentinel.options)

    def test_iterator_outputs_values_without_variable_wiring(self):
        context = {}
        config = {
            "目标数组变量名": "cdkeys_array",
            "当前元素存入变量": "current_cdkey",
        }
        first = logic_iterator_node(
            config,
            {
                "__node_id__": "codes",
                "__value__": ["CODE_A", "CODE_B"],
                "__global_context__": context,
            },
        )
        second = logic_iterator_node(
            config,
            {
                "__node_id__": "codes",
                "__value__": "CODE_A",
                "__global_context__": context,
            },
        )
        finished = logic_iterator_node(
            config,
            {
                "__node_id__": "codes",
                "__value__": "CODE_B",
                "__global_context__": context,
            },
        )

        self.assertEqual(first["value"], "CODE_A")
        self.assertEqual(second["value"], "CODE_B")
        self.assertEqual(finished["active_port"], "队列为空(完成)")

    def test_dynamic_paste_prefers_upstream_value(self):
        with patch("nodes.actions.time.sleep"), patch(
            "nodes.actions.execute_paste_text", return_value=True
        ) as execute:
            result = dynamic_paste_action(
                {"读取变量名": "current_cdkey", "操作前延迟(s)": "0"},
                {
                    "__value__": "UPSTREAM1234",
                    "__global_context__": {"current_cdkey": "LEGACY1234"},
                    "hwnd": 100,
                },
            )
        self.assertEqual(result["value"], "UPSTREAM1234")
        execute.assert_called_once_with(100, "UPSTREAM1234", "DAG_DynamicPaste_current_cdkey")

    def test_crawler_node_emits_array_as_value(self):
        config = {
            "目标URL": "https://example.invalid",
            "触发关键词(可不填)": "兑换码",
            "正则特征": r"[A-Z0-9]+",
            "最大下潜页数": "1",
            "记忆账本键名": "test_codes",
            "结果存入全局变量": "cdkeys_array",
        }
        context = {}
        with patch(
            "functions.func_crawler.hal_scrape_cdkeys",
            return_value=["CODE12345678"],
        ):
            result = fetch_web_data(config, {"__global_context__": context})
        self.assertEqual(result["active_port"], "有待兑换")
        self.assertEqual(result["value"], ["CODE12345678"])
        self.assertEqual(context["cdkeys_array"], ["CODE12345678"])


if __name__ == "__main__":
    unittest.main()
