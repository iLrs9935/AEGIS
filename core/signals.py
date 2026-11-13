"""Single-value data packets shared by the DAG engine and the editor.

Node execution state (Success/Failed/Skipped) belongs to the scheduler.  Data
travelling over an edge has one payload only: ``value``.  A value may itself be
a bool, number, string, list or object.
"""

from ast import literal_eval
import json


BUILTIN_VALUE_TYPES = ("any", "boolean", "number", "string", "object", "array", "null")


class SignalValidationError(ValueError):
    """Raised when an emitted value violates a receiver's input contract."""


def parse_signal_value(value):
    """Parse friendly inspector text into a scalar/container when possible."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"none", "null"}:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        pass
    try:
        return literal_eval(text)
    except (ValueError, SyntaxError):
        return text


def value_type(value):
    """Return the strict AEGIS type name for a Python value.

    ``bool`` is deliberately tested before numbers because Python considers a
    boolean an integer subclass, while workflow contracts must not.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, (list, tuple)):
        return "array"
    return "object"


def _legacy_input_type(config):
    accepted = config.get("accept_types", ["*"])
    if isinstance(accepted, str):
        accepted = [accepted]
    accepted = [str(item).strip().lower() for item in accepted or []]
    if "*" in accepted or not accepted:
        return "any"
    legacy_map = {
        "boolean": "boolean",
        "bool": "boolean",
        "number": "number",
        "string": "string",
        "text": "string",
        "object": "object",
        "array": "array",
        "null": "null",
    }
    # Old state/data/custom tags were routing labels, not safe runtime types.
    return legacy_map.get(accepted[0], "any")


def normalise_signal_config(config=None, output_ports=None, default_input=None):
    """Return the canonical value/output and receiver-contract configuration.

    Older ``emit_types/boolean_value/state_value/output_value`` documents are
    accepted on load.  Only an explicitly configured ``output_value`` migrates
    to the new value override; generated boolean/state metadata is discarded.
    """
    config = config or {}
    default_input = default_input or {"type": "any", "required": False}
    raw_input = config.get("input", {}) or {}
    if "type" in raw_input:
        raw_expected_type = raw_input.get("type")
    elif "accept_type" in config:
        raw_expected_type = config.get("accept_type")
    elif "accept_types" in config:
        raw_expected_type = _legacy_input_type(config)
    else:
        raw_expected_type = default_input.get("type", "any")
    expected_type = str(raw_expected_type).strip().lower()
    if expected_type not in BUILTIN_VALUE_TYPES:
        expected_type = "any"
    required = raw_input.get(
        "required", config.get("input_required", default_input.get("required", False))
    )
    if isinstance(required, str):
        required = required.strip().lower() in {"1", "true", "yes", "是"}

    raw_outputs = config.get("outputs", {}) or {}
    ports = [str(port) for port in (output_ports or raw_outputs.keys() or ["OUT"])]
    outputs = {}
    for port in ports:
        raw = raw_outputs.get(port, {}) or {}
        configured_value = raw.get("value", raw.get("output_value", ""))
        if configured_value is None:
            configured_value = ""
        outputs[port] = {"value": str(configured_value)}

    return {
        "outputs": outputs,
        "input": {
            "type": expected_type or str(default_input.get("type", "any")),
            "required": bool(required),
        },
    }


def _result_value(result_data):
    if "value" in result_data:
        return result_data.get("value")
    if "signal_value" in result_data:
        return result_data.get("signal_value")
    if "signal_bool" in result_data:
        return result_data.get("signal_bool")

    control_keys = {
        "status",
        "active_port",
        "active_ports",
        "signal_state",
    }
    business_data = {
        key: value for key, value in result_data.items() if key not in control_keys
    }
    # Completion-only nodes still emit a useful normal result.
    return business_data or True


def build_signal_envelope(node_id, source_port, result_data, signal_config=None):
    """Build the sole runtime edge payload: one ``value`` plus provenance."""
    result_data = dict(result_data or {})
    config = normalise_signal_config(signal_config, [source_port])
    configured_text = config["outputs"][source_port]["value"].strip()
    value = parse_signal_value(configured_text) if configured_text else _result_value(result_data)
    return {
        "source_id": node_id,
        "source_port": source_port,
        "value": value,
    }


def validate_receiver_input(envelope, signal_config=None):
    """Validate one packet and return it, or fail the current workflow."""
    config = normalise_signal_config(signal_config)
    contract = config["input"]
    if envelope is None:
        if contract["required"]:
            raise SignalValidationError("必需输入没有收到上游 value")
        return None

    value = envelope.get("value")
    if value is None and contract["required"]:
        raise SignalValidationError("必需输入收到 null")

    actual_type = value_type(value)
    expected_type = contract["type"]
    if expected_type != "any" and actual_type != expected_type:
        raise SignalValidationError(
            f"输入类型不合法：需要 {expected_type}，实际收到 {actual_type} ({value!r})"
        )
    return envelope


def receiver_accepts(envelope, signal_config=None):
    """Compatibility helper. New engine code uses strict validation directly."""
    try:
        validate_receiver_input(envelope, signal_config)
        return True
    except SignalValidationError:
        return False
