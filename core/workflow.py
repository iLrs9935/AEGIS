"""Backward-compatible document migration; permissions are never imported."""
from copy import deepcopy
import math


def output_ports(name, config, registry):
    schema = registry[name]["schema"]
    if schema.get("__dynamic_router__"):
        rules = config.get("路由规则", schema.get("路由规则", {}).get("default", []))
        names = {str(rule.get("port", "")).strip() for rule in rules if isinstance(rule, dict)} if isinstance(rules, list) else set()
        if config.get("未匹配时") == "走默认出口":
            names.add(str(config.get("默认出口名称", "默认")).strip() or "默认")
        return names or {"未配置"}
    return set(schema.get("__out_ports__", ["OUT"]))


def migrate_click_modes(document):
    data = deepcopy(document)
    notices = []
    for node in data.get("nodes", []):
        name = node.get("type", node.get("name"))
        if name in {"物理点击", "连续物理点击"}:
            config = node.setdefault("config", {})
            if "坐标模式" not in config:
                config["坐标模式"] = "指定坐标"
                notices.append(f"{node.get('id')}: {name} 已迁移为指定坐标；缺少坐标将失败。"
                               "如需当前位置点击，请在配置中显式选择并保存。")
    if notices:
        meta = data.setdefault("meta", {})
        meta["click_mode_version"] = 1
        meta["click_migration_required_review"] = True
    return data, notices


def validate_document(data, registry):
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), list) or not isinstance(data.get("edges"), list):
        raise ValueError("Workflow must contain nodes and edges arrays")
    def finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Non-finite JSON numbers are unsupported")
        if isinstance(value, dict):
            for item in value.values():
                finite(item)
        elif isinstance(value, list):
            for item in value:
                finite(item)
    finite(data)
    meta = data.get("meta", {})
    groups = data.get("groups", [])
    if not isinstance(meta, dict) or not isinstance(groups, list):
        raise ValueError("Invalid workflow metadata/groups")
    if any(not isinstance(meta[key], str) for key in ("theme", "edge_style") if key in meta):
        raise ValueError("Theme and edge style must be strings")
    ids = []
    nodes = {}
    for node in data["nodes"]:
        node_id = node["id"]
        if not isinstance(node_id, str) or not node_id:
            raise ValueError("Invalid node ID")
        ids.append(node_id)
        nodes[node_id] = node
        if node.get("type", node.get("name")) not in registry:
            raise ValueError(f"Unsupported node: {node_id}")
        if not isinstance(node.get("config", {}), dict):
            raise ValueError("Node config must be an object")
        if not isinstance(node.get("signal_config", {}), dict):
            raise ValueError("Signal config must be an object")
    for item in [*data["nodes"], *groups]:
        if not isinstance(item, dict):
            raise ValueError("Node/group must be an object")
        for key in ("x", "y", "w", "h", "_expanded_height"):
            if key in item and (isinstance(item[key], bool) or not isinstance(item[key], (int, float))):
                raise ValueError("Node/group geometry must contain finite numbers")
    for group in groups:
        if not isinstance(group.get("id"), str) or not isinstance(group.get("name"), str):
            raise ValueError("Group ID/name must be strings")
        if not isinstance(group.get("member_ids", []), list) or any(not isinstance(i, str) for i in group.get("member_ids", [])):
            raise ValueError("Group members must be node ID strings")
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate node IDs")
    for edge in data["edges"]:
        if edge["src_id"] not in ids or edge["tgt_id"] not in ids or edge["tgt_port"] != "IN":
            raise ValueError("Dangling or unsupported workflow edge")
        node = nodes[edge["src_id"]]
        name = node.get("type", node.get("name"))
        ports = output_ports(name, node.get("config", {}), registry)
        if name == "视觉寻图":
            ports |= {"找到目标", "未找到"}  # Explicit legacy migration follows.
        if edge.get("src_port") not in ports:
            raise ValueError("Unsupported source port; refusing to drop a connection")
