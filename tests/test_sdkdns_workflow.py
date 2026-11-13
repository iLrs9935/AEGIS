import json
import unittest
from pathlib import Path

from nodes import NODE_REGISTRY


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / "tests" / "fixtures" / "SDKDNS_确保已连接.json"


class SDKDNSWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
        cls.nodes = {node["id"]: node for node in cls.workflow["nodes"]}

    def test_all_nodes_and_edges_are_loadable(self):
        self.assertEqual(len(self.nodes), len(self.workflow["nodes"]))
        for node in self.nodes.values():
            self.assertIn(node["type"], NODE_REGISTRY)
        for edge in self.workflow["edges"]:
            self.assertIn(edge["src_id"], self.nodes)
            self.assertIn(edge["tgt_id"], self.nodes)

    def test_workflow_reinvokes_existing_sdkdns_to_wake_tray_window(self):
        opener = self.nodes["sdkdns-open"]
        self.assertEqual(
            opener["config"]["已运行时"], "再次调用以唤醒窗口"
        )
        self.assertTrue(opener["config"]["程序路径"].endswith("/SDKDNS.exe"))

    def test_connected_and_disconnected_templates_exist(self):
        for node_id, expected_name in (
            ("sdkdns-check-connected", "1.png"),
            ("sdkdns-check-connect-button", "0.png"),
        ):
            image_path = self.nodes[node_id]["config"]["图片路径"]
            self.assertEqual(Path(image_path).name, expected_name)
            self.assertTrue((ROOT / image_path).is_file())

    def test_click_is_followed_by_wait_and_connected_recheck_loop(self):
        edges = {
            (edge["src_id"], edge["src_port"], edge["tgt_id"])
            for edge in self.workflow["edges"]
        }
        self.assertIn(
            ("sdkdns-route-connect-button", "找到连接按钮", "sdkdns-click-connect"),
            edges,
        )
        self.assertIn(
            ("sdkdns-click-connect", "OUT", "sdkdns-wait-connected"), edges
        )
        self.assertIn(
            ("sdkdns-wait-connected", "OUT", "sdkdns-check-connected"), edges
        )


if __name__ == "__main__":
    unittest.main()
