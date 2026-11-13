import unittest

from core.signals import (
    SignalValidationError,
    build_signal_envelope,
    normalise_signal_config,
    parse_signal_value,
    validate_receiver_input,
    value_type,
)
from nodes.logic import signal_router_node


class ValueSignalTests(unittest.TestCase):
    def test_false_is_a_valid_boolean_value(self):
        envelope = build_signal_envelope(
            "source", "OUT", {"status": "Success", "value": False}, {}
        )
        self.assertIs(envelope["value"], False)
        self.assertEqual(value_type(envelope["value"]), "boolean")
        validate_receiver_input(
            envelope, {"input": {"type": "boolean", "required": True}}
        )

    def test_string_false_does_not_satisfy_boolean_contract(self):
        with self.assertRaises(SignalValidationError):
            validate_receiver_input(
                {"value": "false"},
                {"input": {"type": "boolean", "required": True}},
            )

    def test_json_object_override_uses_json_boolean_literals(self):
        self.assertEqual(
            parse_signal_value('{"found": false}'), {"found": False}
        )

    def test_legacy_state_metadata_is_not_preserved_as_a_second_value(self):
        legacy = {
            "outputs": {
                "OUT": {
                    "emit_types": ["boolean", "state"],
                    "boolean_value": "false",
                    "state_value": "ready",
                    "output_value": "",
                }
            },
            "accept_types": ["boolean"],
        }
        self.assertEqual(
            normalise_signal_config(legacy, ["OUT"]),
            {
                "outputs": {"OUT": {"value": ""}},
                "input": {"type": "boolean", "required": False},
            },
        )


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "节点标签": "test",
            "输入选择": "最后一个",
            "匹配模式": "首个匹配",
            "路由规则": [
                {
                    "port": "找到目标",
                    "path": "found",
                    "operator": "等于",
                    "target": "true",
                },
                {
                    "port": "未找到",
                    "path": "found",
                    "operator": "等于",
                    "target": "false",
                },
            ],
            "未匹配时": "终止工作流",
        }

    def test_router_selects_port_and_forwards_original_value(self):
        value = {"found": True, "target_x": 10, "target_y": 20}
        result = signal_router_node(
            self.config, {"__signals__": [{"value": value}]}
        )
        self.assertEqual(result["active_ports"], ["找到目标"])
        self.assertIs(result["value"], value)

    def test_missing_rule_path_is_a_hard_failure(self):
        with self.assertRaises(ValueError):
            signal_router_node(
                self.config, {"__signals__": [{"value": {"other": True}}]}
            )


if __name__ == "__main__":
    unittest.main()
