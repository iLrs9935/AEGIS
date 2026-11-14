"""Capability checks for workflow programs, not a Python/OS sandbox.

All built-ins are individually reviewed. New/unknown nodes fail closed until
their effects have been classified here. JSON never carries executable grants.
"""
from dataclasses import dataclass
import hashlib
import json


READ_ONLY = "read_only"
DESKTOP = "desktop_interaction"
FILES = "file_modification"
PROCESS = "process_control"
SYSTEM = "system_control"
EXTERNAL = "external_service"
WORKFLOW = "workflow_execution"
EFFECTS = {
    DESKTOP: "Mouse/keyboard input, clipboard or window focus / 鼠标、键盘、剪贴板或窗口焦点",
    FILES: "Create/change/delete local data / 创建、修改或删除本地数据",
    PROCESS: "Start/stop programs, including arbitrary command interpreters / 启停程序（含任意命令解释器）",
    SYSTEM: "Power, application termination or shared native-model resources / 电源、退出终端或共享原生模型资源",
    EXTERNAL: "Network requests or remote notifications / 网络请求或远程通知",
    WORKFLOW: "Load another workflow; it needs a fresh review / 加载其他图纸，目标需重新审查",
}

# Reviewed against the implementations, including implicit side effects:
# vision may activate a window; crawler launches Selenium and writes a ledger;
# reliable notifications write an outbox; chat persistence writes SQLite.
NODE_CAPABILITIES = {
    **{name: frozenset({READ_ONLY}) for name in (
        "信号暂存器", "信号中继器", "逻辑与门", "逻辑或门", "逻辑非门", "数组遍历器", "信号分流器",
        "文本输入", "多文本合并", "文本展示", "等待时间", "脉冲计时器", "状态检测", "读取记忆",
        "构建提示词", "加载并组装对话", "大模型推理",
        "OK-WW监控初始化", "OK-WW任务监控",
    )},
    **{name: frozenset({DESKTOP}) for name in (
        "物理点击", "连续物理点击", "持续滚轮", "强制粘贴", "键盘操作", "动态变量粘贴",
        "唤醒并置顶窗口", "视觉寻图",
    )},
    **{name: frozenset({FILES}) for name in ("写入记忆", "删除记忆", "追加并保存对话", "记录兑换码结果")},
    "启动程序": frozenset({PROCESS}),
    "结束进程": frozenset({PROCESS}),
    "OK-WW安全清理": frozenset({PROCESS}),
    "系统休眠": frozenset({SYSTEM}),
    "加载大模型": frozenset({SYSTEM}),
    "卸载大模型": frozenset({SYSTEM}),
    "运行新图纸": frozenset({WORKFLOW}),
    "Bark通知": frozenset({EXTERNAL}),
    "可靠Bark通知": frozenset({EXTERNAL, FILES}),
    "通用网页嗅探": frozenset({EXTERNAL, PROCESS, FILES}),
}


class PermissionDenied(RuntimeError):
    pass


def digest(nodes, edges, source):
    content = json.dumps([nodes, edges, source], sort_keys=True, ensure_ascii=False,
                         allow_nan=False, separators=(",", ":"))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Finding:
    node_id: str
    name: str
    capabilities: frozenset
    details: tuple = ()


@dataclass(frozen=True)
class Review:
    fingerprint: str
    source: str
    findings: tuple
    unknown: tuple
    node_specs: tuple

    @property
    def required(self):
        return frozenset(cap for finding in self.findings for cap in finding.capabilities)

    def describe(self):
        lines = [f"Source / 来源: {self.source}; trust / 信任: untrusted until approved",
                 f"Fingerprint: {self.fingerprint[:16]}"]
        for finding in self.findings:
            lines.append(f"• {finding.node_id}: {finding.name}")
            lines.extend(f"  {detail}" for detail in finding.details)
            lines.extend(f"  {cap}: {EFFECTS[cap]}" for cap in sorted(finding.capabilities))
        if self.unknown:
            lines.append("Unsupported / 未识别或不支持: " + ", ".join(self.unknown))
        lines.append("Approve this exact run only? / 仅授权本次运行？")
        return "\n".join(lines)


def review_workflow(nodes, edges, source="local"):
    from nodes import NODE_REGISTRY
    from .workflow import output_ports
    if source not in {"local", "external", "ai"}:
        raise ValueError("Unknown workflow source")
    findings, unknown = [], []
    for node_id, info in nodes.items():
        name = info.get("name")
        if name not in NODE_REGISTRY or name not in NODE_CAPABILITIES:
            unknown.append(f"{node_id}: {name}")
            continue
        if not info.get("is_disabled", False):
            caps = NODE_CAPABILITIES[name] - {READ_ONLY}
            if caps:
                config = info.get("config", {})
                details = ()
                if name in {"物理点击", "连续物理点击"}:
                    details = ("Coordinate mode / 坐标模式: " + str(config.get("坐标模式", "missing / 缺失")),)
                elif name == "系统休眠":
                    details = ("Action / 执行动作: " + str(config.get("执行动作", "S4休眠并退出终端")),)
                elif name == "删除记忆" and config.get("目标键名 (输入 * 擦除全部)") == "*":
                    details = ("Delete ALL persisted memory / 删除全部持久化记忆",)
                findings.append(Finding(node_id, name, caps, details))
    for src, src_port, tgt, tgt_port in edges:
        if src not in nodes or tgt not in nodes:
            unknown.append(f"Dangling edge: {src} -> {tgt}")
        elif tgt_port != "IN" or (
            nodes[src].get("name") in NODE_REGISTRY
            and src_port not in output_ports(nodes[src]["name"], nodes[src].get("config", {}), NODE_REGISTRY)
        ):
            unknown.append(f"Unsupported edge port: {src}:{src_port} -> {tgt}:{tgt_port}")
    specs = tuple((node_id, digest({node_id: info}, [], source)) for node_id, info in nodes.items())
    return Review(digest(nodes, edges, source), source, tuple(findings), tuple(unknown), specs)


@dataclass(frozen=True)
class ExecutionPolicy:
    fingerprint: str
    grants: frozenset = frozenset()
    read_only: bool = False
    source: str = "local"
    node_specs: tuple = ()

    @classmethod
    def authorize(cls, review, approved=(), *, read_only=False):
        if review.unknown:
            raise PermissionDenied("Unsupported nodes/edges: " + ", ".join(review.unknown))
        grants = frozenset(approved)
        if not grants <= EFFECTS.keys():
            raise PermissionDenied("Unknown capability grant")
        if read_only and review.required:
            raise PermissionDenied("Read-only safe mode rejects desktop, file, process, system, network and workflow effects")
        missing = review.required - grants
        if missing:
            raise PermissionDenied("Explicit authorization required: " + ", ".join(sorted(missing)))
        return cls(review.fingerprint, grants, read_only, review.source, review.node_specs)

    def check_node(self, node_id, info, fingerprint):
        if dict(self.node_specs).get(node_id) != digest({node_id: info}, [], self.source):
            raise PermissionDenied("Node configuration changed after review")
        self.check(info["name"], fingerprint)

    def check(self, name, fingerprint):
        if fingerprint != self.fingerprint:
            raise PermissionDenied("Workflow changed after review; review again")
        if name not in NODE_CAPABILITIES:
            raise PermissionDenied(f"Unclassified node: {name}")
        required = NODE_CAPABILITIES[name] - {READ_ONLY}
        if required - self.grants or (self.read_only and required):
            raise PermissionDenied(f"Unauthorized node: {name}")
