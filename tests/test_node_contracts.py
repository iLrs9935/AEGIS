"""Authored registry-wide contracts. Native actions/services/persistence are mocked.

Subtests are scenarios, not additional top-level test counts. Pure nodes have no
external failure scenario; optional model, browser and remote backends are doubles.
"""
from contextlib import ExitStack
from copy import deepcopy
import time
import unittest
from unittest.mock import Mock, patch

from core.context import ExecutionContext
from core.engine import NodeWorker
from core.event_bus import bus
from core.security import ExecutionPolicy, review_workflow
from functions.func_actions import stop_event
from nodes import NODE_REGISTRY
from nodes.okww import STATE_KEY


# Config, value/input overrides, expected output subset. These are behavior
# examples independent of the registry schemas (which are UI defaults).
CASES = {
    "文本输入": ({"文本内容": "hello", "存入变量名": "text"}, {}, {"active_port": "文本输出"}),
    "多文本合并": ({"读取变量A": "a", "读取变量B": "b", "存入变量名": "merged", "连接符": "|"}, {}, {"active_port": "合并完成"}),
    "文本展示": ({"读取变量名": "a"}, {}, {"active_port": "通过"}),
    "信号暂存器": ({"变量名": "flag", "写入值": "True"}, {}, {"active_port": "继续"}),
    "信号中继器": ({"控制变量名": "flag", "通过条件": "False"}, {}, {"active_port": "通过"}),
    "逻辑与门": ({"检测信号列表": "yes"}, {}, {"active_port": "全选通"}),
    "逻辑或门": ({"检测信号列表": "flag,yes"}, {}, {"active_port": "有选通"}),
    "逻辑非门": ({"检测变量名": "flag"}, {}, {"active_port": "无信号(通过)"}),
    "数组遍历器": ({"目标数组变量名": "queue", "当前元素存入变量": "item"}, {}, {"value": "one"}),
    "信号分流器": ({"路由规则": [{"port": "yes", "path": "", "operator": "等于", "target": "true"}]}, {"__signals__": [{"value": True}]}, {"active_ports": ["yes"], "value": True}),
    "等待时间": ({"等待时长(s)": "0"}, {}, {}),
    "脉冲计时器": ({"监测间隔(s)": "0", "最大超时(s)": "100"}, {}, {"active_port": "执行脉冲"}),
    "状态检测": ({"目标名称": "test-window"}, {}, {"active_port": "已运行", "hwnd": 99}),
    "物理点击": ({"坐标模式": "指定坐标", "操作前延迟(s)": "0"}, {"target_x": 10, "target_y": 20}, {}),
    "连续物理点击": ({"坐标模式": "指定坐标", "点击次数": "1"}, {"target_x": 10, "target_y": 20}, {}),
    "持续滚轮": ({"持续时长(s)": "0.1"}, {}, {"active_port": "滚动完成"}),
    "强制粘贴": ({"粘贴文本": "text"}, {"hwnd": 99}, {}),
    "键盘操作": ({"操作类型": "敲击单键", "输入方式": "后台消息(PostMessage)", "按键名(如 F/SPACE/ENTER) 或 文本": "W"}, {"hwnd": 99}, {"hwnd": 99}),
    "动态变量粘贴": ({"输入方式": "后台消息(PostMessage)"}, {"hwnd": 99, "__value__": "CODE1234"}, {"active_port": "已粘贴", "value": "CODE1234"}),
    "视觉寻图": ({"图片路径": "images/test.png", "执行模式": "后台(静默寻图)"}, {}, {"target_x": 10, "target_y": 20, "hwnd": 99}),
    "启动程序": ({"程序路径": "test-program.exe", "等待启动(s)": "0"}, {}, {"pid": 42}),
    "结束进程": ({"目标名称(如 鸣潮 或 ok-ww.exe)": "test-process.exe"}, {}, {"active_port": "已清理"}),
    "系统休眠": ({"执行动作": "保留终端(不休眠)"}, {"__value__": "preserved"}, {"value": "preserved"}),
    "运行新图纸": ({"目标图纸路径": "examples/workflows/01_hello_text.json", "点火倒计时(s)": "0"}, {}, {"status": "Jump_Triggered"}),
    "唤醒并置顶窗口": ({"目标窗口标题": "test-window", "操作前延迟(s)": "0", "操作后稳定延迟(s)": "0"}, {}, {"active_port": "已唤醒(继续)"}),
    "写入记忆": ({"记忆键名 (Key)": "test", "要写入的值 (可接线)": "saved"}, {}, {"当前值": "saved"}),
    "读取记忆": ({"记忆键名 (Key)": "test"}, {}, {"active_port": "提取成功", "提取的值": "remembered"}),
    "删除记忆": ({"目标键名 (输入 * 擦除全部)": "test"}, {}, {"active_port": "已清理"}),
    "加载大模型": ({"模型路径": "test.gguf", "GPU层数": "0"}, {}, {"active_port": "加载成功"}),
    "卸载大模型": ({}, {}, {"active_port": "已释放"}),
    "构建提示词": ({"系统指令": "system", "动态内容": "{a}", "输出变量名": "prompt"}, {}, {"active_port": "构建完成"}),
    "大模型推理": ({"读取Prompt变量": "prompt", "存入结果变量": "reply"}, {}, {"active_port": "推理完成"}),
    "加载并组装对话": ({"记忆键名": "history", "读取用户输入变量": "a", "存入对话组变量": "history"}, {}, {"active_port": "组装完成"}),
    "追加并保存对话": ({"读取对话组变量": "history", "读取AI回复变量": "reply"}, {}, {"active_port": "保存完成"}),
    "通用网页嗅探": ({"目标URL": "https://example.com", "正则特征": "[A-Z]+", "结果存入全局变量": "codes"}, {}, {"active_port": "有待兑换", "value": ["CODE1234"]}),
    "记录兑换码结果": ({}, {"__value__": "CODE1234"}, {"active_port": "继续下一个", "value": "CODE1234"}),
    "Bark通知": ({"Bark推送地址": "https://api.day.app/test-key"}, {}, {}),
    "可靠Bark通知": ({"Bark推送地址": "https://api.day.app/test-key"}, {"__value__": {"state": "success"}}, {"value": {"state": "success", "notification": "delivered"}}),
    "OK-WW监控初始化": ({}, {}, {"active_port": "允许启动"}),
    "OK-WW任务监控": ({}, {}, {"active_port": "成功"}),
    "OK-WW安全清理": ({"确认超时(s)": "0"}, {}, {"active_port": "已清理"}),
}


class NodeContractTests(unittest.TestCase):
    def setUp(self):
        stop_event.clear()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.doubles = {}
        def stub(path, value=None):
            self.doubles[path] = self.stack.enter_context(patch(path, return_value=value))
        for name in ("SetCursorPos",):
            stub("nodes.actions.win32api." + name)
        self.stack.enter_context(patch("nodes.actions.win32api.GetSystemMetrics", side_effect=lambda i: {76: 0, 77: 0, 78: 1920, 79: 1080}[i]))
        stub("nodes.actions.win32gui.IsWindow", True)
        stub("nodes.actions.win32gui.GetForegroundWindow", 99)
        for name in ("execute_global_mouse_action", "execute_background_click", "execute_rapid_click", "execute_mouse_wheel", "execute_paste_text", "execute_key_spec", "execute_post_message_key_spec", "execute_post_message_text", "execute_type_string"):
            stub("nodes.actions." + name, True)
        stub("nodes.actions.time.sleep")
        for name, value in (("execute_start_process", (True, 42)), ("execute_sleep", True), ("execute_delayed_hibernate", True), ("execute_self_destruct", None), ("kill_specific_processes", None), ("kill_windows_by_titles", None), ("get_target_window", (99, (0, 0, 100, 100))), ("force_activate_window", True)):
            stub("nodes.system." + name, value)
        self.stack.enter_context(patch("nodes.system.bus"))
        stub("nodes.timers.execute_sleep", True)
        stub("functions.func_system.execute_sleep", True)
        stub("functions.func_window.force_activate_window", True)
        stub("nodes.triggers.get_target_window", (99, (0, 0, 100, 100)))
        stub("nodes.triggers.is_process_running", True)
        stub("functions.func_window.get_target_window", (99, (0, 0, 100, 100)))
        stub("functions.func_vision.execute_template_match", ((10, 20), 1.0))
        for name, value in (("write", True), ("read", "remembered"), ("delete", True), ("wipe_all", True)):
            stub("nodes.memory.vault." + name, value)
        for name, value in (("load_model", True), ("unload_model", None), ("generate_chat", "answer")):
            stub("nodes.ai." + name, value)
        stub("functions.func_crawler.hal_scrape_cdkeys", ["CODE1234"])
        stub("functions.func_crawler.mark_cdkey_processed")
        stub("nodes.notifications.execute_bark_push", True)
        stub("nodes.notifications.execute_reliable_bark_push", {"delivered": True, "queued": False})
        stub("nodes.okww._relevant_processes", [])
        stub("nodes.okww.snapshot_log_offsets", {})
        stub("nodes.okww.read_appended_logs", "success")
        stub("nodes.okww.classify_log_update", {"state": "success", "summary": "done"})
        stub("nodes.okww.session_owned_processes", [])
        stub("nodes.okww.wait_until_no_owned_processes", [])
        stub("nodes.okww.terminate_process_tree")
        stub("nodes.okww.execute_sleep", True)

    def inputs(self, overrides=None):
        context = ExecutionContext()
        context.update(a="A", b="B", flag=False, yes=True, queue=["one"],
                       prompt="question", reply="answer", history=[])
        context[STATE_KEY] = {
            "attempt": 1, "max_attempts": 3, "workflow_started": time.monotonic(),
            "settings": {"log_directory": "test-logs", "internal_log_directory": "test-inner"},
            "log_offsets": {}, "terminal_state": "running", "baseline_identities": [],
        }
        return {"__global_context__": context, "__node_id__": "contract", **deepcopy(overrides or {})}

    def invoke(self, name, config=None, inputs=None):
        normal_config, normal_inputs, _ = CASES[name]
        return NODE_REGISTRY[name]["func"](
            deepcopy(normal_config if config is None else config),
            self.inputs(normal_inputs) if inputs is None else inputs,
        )

    def test_every_registered_node_normal_output_and_context_contract(self):
        self.assertEqual(set(CASES), set(NODE_REGISTRY))
        for name, (config, overrides, expected) in CASES.items():
            with self.subTest(node=name):
                inputs = self.inputs(overrides)
                result = self.invoke(name, inputs=inputs)
                for key, value in {"status": "Success", **expected}.items():
                    self.assertEqual(result.get(key), value)
                context = inputs["__global_context__"]
                if name == "文本输入":
                    self.assertEqual(context["text"], "hello")
                elif name == "多文本合并":
                    self.assertEqual(context["merged"], "A|B")
                elif name == "数组遍历器":
                    self.assertEqual(context["queue"], [])
                    self.assertEqual(context["item"], "one")
                elif name == "构建提示词":
                    self.assertEqual(context["prompt"], "System: system\nUser: A\nAssistant:")
                elif name == "大模型推理":
                    self.assertEqual(context["reply"], "answer")
                elif name == "追加并保存对话":
                    self.assertEqual(context["history"], [{"role": "assistant", "content": "answer"}])
                elif name == "通用网页嗅探":
                    self.assertEqual(context["codes"], ["CODE1234"])

    def test_missing_inputs_follow_documented_defaults_or_fail_closed(self):
        failures = {"物理点击", "连续物理点击", "动态变量粘贴", "信号分流器", "记录兑换码结果"}
        ports = {"数组遍历器": "队列为空(完成)", "OK-WW任务监控": "最终失败", "OK-WW安全清理": "清理失败", "多文本合并": "缺少变量", "大模型推理": "推理报错"}
        for name in CASES:
            with self.subTest(node=name):
                try:
                    result = self.invoke(name, inputs={})
                except Exception as exc:
                    self.assertIn(name, failures, f"Unexpected missing-input error: {exc}")
                else:
                    if name in failures:
                        self.assertIn(result["status"], {"Error", "Failed"})
                    else:
                        self.assertIn(result["status"], {"Success", "Jump_Triggered"})
                        if name in ports:
                            self.assertEqual(result.get("active_port"), ports[name])

    def test_missing_configuration_and_zero_length_boundaries(self):
        required = {"状态检测", "视觉寻图", "启动程序", "结束进程", "运行新图纸",
                    "写入记忆", "读取记忆", "删除记忆", "信号分流器", "通用网页嗅探"}
        # Explicitly keep power, keyboard and clipboard seams mocked even when
        # exercising their old defaults. No real action may escape this fixture.
        self.doubles["nodes.notifications.execute_bark_push"].reset_mock()
        for name in CASES:
            with self.subTest(node=name):
                try:
                    result = self.invoke(name, config={})
                except Exception:
                    self.assertIn(name, required)
                else:
                    self.assertNotIn(name, required)
                    if name in {"物理点击", "连续物理点击", "系统休眠"}:
                        self.assertIn(result["status"], {"Error", "Failed"})
                    else:
                        self.assertIn(result["status"], {"Success", "Jump_Triggered"})

    def test_wrong_input_container_is_rejected_by_worker_for_every_node(self):
        for name, (config, _, _) in CASES.items():
            with self.subTest(node=name):
                info = {"name": name, "config": config}
                review = review_workflow({"n": info}, [])
                policy = ExecutionPolicy.authorize(review, review.required)
                statuses = []
                def record(node_id, status, result):
                    statuses.append(status)
                bus.node_status_changed.connect(record)
                try:
                    NodeWorker("n", name, config, [], policy=policy,
                               fingerprint=review.fingerprint, node_spec=info).run()
                    self.assertEqual(statuses[-1], "Failed")
                finally:
                    bus.node_status_changed.disconnect(record)

    def test_empty_and_boundary_data_branches(self):
        samples = [
            ("文本输入", {"文本内容": "", "存入变量名": "empty"}, {}, "文本输出"),
            ("逻辑与门", {"检测信号列表": " , "}, {}, "等待中"),
            ("逻辑或门", {"检测信号列表": ""}, {}, "全无信号"),
            ("信号中继器", {"控制变量名": "yes", "通过条件": "False"}, {}, "阻断"),
            ("逻辑非门", {"检测变量名": "yes"}, {}, "有信号(阻断)"),
            ("数组遍历器", {}, {"__value__": []}, "队列为空(完成)"),
            ("脉冲计时器", {"最大超时(s)": "0"}, {}, "超时跳出"),
            ("加载并组装对话", {"最大上下文条数": "0"}, {}, "组装完成"),
            ("构建提示词", {"动态内容": "{missing}"}, {}, "构建完成"),
        ]
        for name, config, overrides, port in samples:
            with self.subTest(node=name):
                self.assertEqual(self.invoke(name, config, self.inputs(overrides))["active_port"], port)
        self.doubles["nodes.memory.vault.read"].return_value = None
        self.assertEqual(self.invoke("读取记忆")["active_port"], "无此记忆")
        self.invoke("删除记忆", {"目标键名 (输入 * 擦除全部)": "*"})
        self.doubles["nodes.memory.vault.wipe_all"].assert_called_once()

    def test_external_dependency_failure_then_normal_recovery(self):
        dependencies = {
            "物理点击": "nodes.actions.execute_global_mouse_action",
            "连续物理点击": "nodes.actions.execute_rapid_click",
            "持续滚轮": "nodes.actions.execute_mouse_wheel",
            "强制粘贴": "nodes.actions.execute_paste_text",
            "键盘操作": "nodes.actions.execute_post_message_key_spec",
            "动态变量粘贴": "nodes.actions.execute_post_message_text",
            "视觉寻图": "functions.func_vision.execute_template_match",
            "启动程序": "nodes.system.execute_start_process",
            "结束进程": "nodes.system.kill_windows_by_titles",
            "唤醒并置顶窗口": "nodes.system.force_activate_window",
            "写入记忆": "nodes.memory.vault.write",
            "读取记忆": "nodes.memory.vault.read",
            "删除记忆": "nodes.memory.vault.delete",
            "加载大模型": "nodes.ai.load_model",
            "卸载大模型": "nodes.ai.unload_model",
            "大模型推理": "nodes.ai.generate_chat",
            "加载并组装对话": "nodes.memory.vault.read",
            "追加并保存对话": "nodes.memory.vault.write",
            "通用网页嗅探": "functions.func_crawler.hal_scrape_cdkeys",
            "记录兑换码结果": "functions.func_crawler.mark_cdkey_processed",
            "Bark通知": "nodes.notifications.execute_bark_push",
            "可靠Bark通知": "nodes.notifications.execute_reliable_bark_push",
            "OK-WW监控初始化": "nodes.okww._relevant_processes",
            "OK-WW任务监控": "nodes.okww.read_appended_logs",
            "OK-WW安全清理": "nodes.okww._relevant_processes",
        }
        handled = {"唤醒并置顶窗口": "已唤醒(继续)", "结束进程": "已清理", "大模型推理": "推理报错", "OK-WW监控初始化": "环境占用", "OK-WW任务监控": "失败可重试", "OK-WW安全清理": "清理失败"}
        for name, path in dependencies.items():
            with self.subTest(node=name):
                double = self.doubles[path]
                double.side_effect = OSError("dependency unavailable")
                try:
                    if name in handled:
                        self.assertEqual(self.invoke(name)["active_port"], handled[name])
                    else:
                        with self.assertRaises(OSError):
                            self.invoke(name)
                finally:
                    double.side_effect = None
                expected = {"status": "Success", **CASES[name][2]}
                result = self.invoke(name)
                for key, value in expected.items():
                    self.assertEqual(result.get(key), value)

    def test_specific_wrong_field_types_fail_before_persistence_or_inference(self):
        for name, field in (("文本输入", "存入变量名"), ("信号暂存器", "变量名"),
                            ("信号中继器", "控制变量名"), ("逻辑与门", "检测信号列表"),
                            ("逻辑或门", "检测信号列表"), ("逻辑非门", "检测变量名"),
                            ("多文本合并", "读取变量A"), ("文本展示", "读取变量名"),
                            ("写入记忆", "记忆键名 (Key)"), ("读取记忆", "记忆键名 (Key)"),
                            ("删除记忆", "目标键名 (输入 * 擦除全部)"),
                            ("状态检测", "目标名称"), ("结束进程", "目标名称(如 鸣潮 或 ok-ww.exe)"),
                            ("加载并组装对话", "记忆键名"), ("追加并保存对话", "记忆键名"),
                            ("通用网页嗅探", "最大下潜页数"), ("记录兑换码结果", "记忆账本键名"),
                            ("等待时间", "等待时长(s)"), ("脉冲计时器", "最大超时(s)")):
            with self.subTest(node=name):
                config = {**CASES[name][0], field: []}
                with self.assertRaises((TypeError, AttributeError, ValueError)):
                    self.invoke(name, config)
