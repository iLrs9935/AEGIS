# core/engine.py
# AEGIS之心 v1.1
import networkx as nx
from PyQt6.QtCore import QObject, QRunnable, QThreadPool, QTimer, pyqtSlot

from nodes import NODE_REGISTRY

from .config import resolve_config
from .event_bus import bus
from .signals import (
    SignalValidationError,
    build_signal_envelope,
    validate_receiver_input,
    value_type,
)

# ====== 新增：引入全局刹车信号 ======
try:
    from functions.func_actions import stop_event
except ImportError:
    stop_event = None
# ====================================


class NodeWorker(QRunnable):
    def __init__(
        self,
        node_id: str,
        node_name: str,
        config: dict,
        inputs: dict,
        is_disabled: bool = False,
    ):
        super().__init__()
        self.node_id = node_id
        self.node_name = node_name
        self.config = config
        self.inputs = inputs
        self.is_disabled = is_disabled

    def run(self):
        # ====== 新增防线：引擎级拦截 ======
        # 如果排到这个节点时已经刹车了，直接取消并流产
        if stop_event and stop_event.is_set():
            bus.log_emitted.emit(
                "WARN",
                "Engine",
                f"🛑 拦截生效！[{self.node_name}] 因紧急刹车被取消执行。",
            )
            bus.node_status_changed.emit(self.node_id, "Cancelled", "")
            return
        # ==================================

        if self.is_disabled:
            bus.log_emitted.emit(
                "WARN",
                "Engine",
                f"🚫 [{self.node_name}] 被手动禁用，转化为幽灵信号向下穿透。",
            )
            bus.node_status_changed.emit(self.node_id, "Skipped", "{}")
            return

        bus.node_status_changed.emit(self.node_id, "Running", "")
        try:
            node_meta = NODE_REGISTRY.get(self.node_name)
            func = node_meta["func"]

            result_data = func(resolve_config(self.config), self.inputs)

            # Long-running HAL functions return as soon as they observe the
            # shared stop event. Never route their partial result downstream.
            if stop_event and stop_event.is_set():
                bus.node_status_changed.emit(self.node_id, "Cancelled", "")
                return

            if not isinstance(result_data, dict):
                raise TypeError("节点必须返回包含 value 的字典结果")

            status = result_data.get("status", "Success")
            if status in {"Error", "Failure", "Failed"}:
                status = "Failed"
            bus.node_status_changed.emit(self.node_id, status, str(result_data))

        except Exception as e:
            if stop_event and stop_event.is_set():
                bus.node_status_changed.emit(self.node_id, "Cancelled", "")
                return
            bus.log_emitted.emit(
                "ERROR", "Engine", f"❌ [{self.node_name}] 错误: {str(e)}"
            )
            bus.node_status_changed.emit(self.node_id, "Failed", "")


class DAGEngine(QObject):
    def __init__(self):
        super().__init__()
        self.thread_pool = QThreadPool.globalInstance()
        # MultiDiGraph keeps deliberate parallel connections distinct.
        self.graph = nx.MultiDiGraph()
        self.node_data_map = {}
        self.results_cache = {}
        self.node_locks = {}
        self.execution_failed = False
        self.is_running = False
        self.active_nodes = set()
        bus.node_status_changed.connect(self._on_node_status_changed)

    def load_from_ui(self, nodes_info: dict, edges_data: list):
        self.graph.clear()
        self.node_data_map = nodes_info
        self.results_cache = {}

        for node_id in nodes_info:
            self.graph.add_node(node_id)

        # 【核心修复】：用一个独立的“影子图”来做纯净测谎
        shadow_graph = nx.MultiDiGraph()
        shadow_graph.add_nodes_from(self.graph.nodes())

        # 【黑魔法 1：拓扑找环，精准标记时光回溯线】
        for edge_index, (src, src_p, tgt, tgt_p) in enumerate(edges_data):
            signal_key = f"{src}:{src_p}:{tgt}:{tgt_p}:{edge_index}"
            # 真实图加上连线
            edge_key = self.graph.add_edge(
                src,
                tgt,
                src_port=src_p,
                tgt_port=tgt_p,
                is_feedback=False,
                signal_key=signal_key,
            )
            # 影子图同步加线，准备测谎
            shadow_key = shadow_graph.add_edge(src, tgt)

            try:
                # 在影子图里查环
                nx.find_cycle(shadow_graph, orientation="original")

                # 如果没报错，说明刚才加的这根线导致了死循环！
                # 1. 真实图中，将它降维成回溯线
                self.graph[src][tgt][edge_key]["is_feedback"] = True
                # 2. 【最关键一步】从影子图中把这根毒线拔掉！防止它污染后续的正常连线检测
                shadow_graph.remove_edge(src, tgt, shadow_key)

                bus.log_emitted.emit(
                    "WARN",
                    "Engine",
                    "🌀 精准识别出闭环！已将连线降维为『时光回溯线』。",
                )
            except nx.NetworkXNoCycle:
                # 没环，一切正常放行
                pass

    def start_execution(self):
        if self.is_running:
            bus.log_emitted.emit(
                "WARN", "Engine", "⛔ 工作流仍在执行中，本次重复点火已拦截。"
            )
            return False

        self.global_context = {}
        self.node_locks = {}
        self.execution_failed = False
        self.active_nodes = set()
        self.is_running = True

        for n in self.graph.nodes():
            forward_in_degree = sum(
                1
                for u, v, d in self.graph.in_edges(n, data=True)
                if not d.get("is_feedback", False)
            )
            # 🛠️ 核心改造 1：废除简单的数字计数，改用信号字典，记住每一个信号的来源！
            self.node_locks[n] = {
                "total": forward_in_degree,
                # {edge signal_key: {kind, source_id, envelope}}
                "signals": {},
            }
            bus.node_status_changed.emit(n, "Idle", "")

        start_nodes = [n for n, locks in self.node_locks.items() if locks["total"] == 0]
        if not start_nodes:
            bus.log_emitted.emit("ERROR", "Engine", "找不到启动起点！")
            self.is_running = False
            return False

        for n_id in start_nodes:
            self._dispatch_node(n_id)
        return True

    def _dispatch_node(self, node_id: str, injected_signals=None):
        if self.execution_failed or (stop_event and stop_event.is_set()):
            self._cancel_execution()
            return
        node_inputs = {}
        received_signals = []
        signal_records = self.node_locks.get(node_id, {}).get("signals", {})
        for pred, _, edge_key, edge_data in self.graph.in_edges(
            node_id, keys=True, data=True
        ):
            record = signal_records.get(edge_data.get("signal_key", edge_key), {})
            signal_kind = (
                record.get("kind") if isinstance(record, dict) else record
            )
            if signal_kind != "Trigger":
                continue
            node_inputs.update(self.results_cache.get(pred, {}))
            envelope = record.get("envelope") if isinstance(record, dict) else None
            if envelope:
                received_signals.append(envelope)
                if isinstance(envelope.get("value"), dict):
                    node_inputs.update(envelope["value"])

        # Feedback edges trigger immediately instead of joining the normal
        # dependency lock, but their typed envelope still reaches the node.
        for envelope in injected_signals or []:
            if envelope:
                received_signals.append(envelope)
                if isinstance(envelope.get("value"), dict):
                    node_inputs.update(envelope["value"])

        target_signal_config = self.node_data_map.get(node_id, {}).get(
            "signal_config", {}
        )
        try:
            if received_signals:
                for envelope in received_signals:
                    validate_receiver_input(envelope, target_signal_config)
            else:
                validate_receiver_input(None, target_signal_config)
        except SignalValidationError as exc:
            self._abort_execution(
                f"节点 [{self.node_data_map.get(node_id, {}).get('name', node_id)}] 输入校验失败：{exc}",
                node_id,
            )
            return

        # 【微创补丁 2】：悄悄把记忆体和节点 ID 塞进 inputs 里传给节点
        node_inputs["__global_context__"] = getattr(self, "global_context", {})
        node_inputs["__node_id__"] = node_id
        node_inputs["__signals__"] = received_signals
        node_inputs["__values__"] = [signal.get("value") for signal in received_signals]
        node_inputs["__value__"] = (
            received_signals[-1].get("value") if received_signals else None
        )

        info = self.node_data_map[node_id]
        worker = NodeWorker(
            node_id,
            info["name"],
            info["config"],
            node_inputs,
            info.get("is_disabled", False),
        )
        self.active_nodes.add(node_id)
        self.thread_pool.start(worker)

    def _schedule_finish_check(self):
        # Status propagation can be recursive (Skipped branches). Defer the
        # check until the complete routing stack has had a chance to dispatch.
        QTimer.singleShot(0, self._finish_if_idle)

    def _finish_if_idle(self):
        if not self.is_running or self.active_nodes:
            return
        self.is_running = False
        cancelled = bool(stop_event and stop_event.is_set())
        if cancelled:
            bus.log_emitted.emit("WARN", "Engine", "🛑 工作流已完全停止。")
        elif not self.execution_failed:
            bus.log_emitted.emit("SUCCESS", "Engine", "✅ 工作流执行完成。")
        bus.dag_completed.emit("cancelled" if cancelled else "finished", not self.execution_failed)

    def _cancel_execution(self):
        if not self.execution_failed:
            self.execution_failed = True
        self._schedule_finish_check()

    def _reset_downstream(self, start_node: str):
        """【量子状态坍缩】顺着正向线清除下游，但绝不洗掉来自循环外部的记忆！"""
        descendants = set()

        def dfs(n):
            for _, v, d in self.graph.out_edges(n, data=True):
                if not d.get("is_feedback", False) and v not in descendants:
                    descendants.add(v)
                    dfs(v)

        dfs(start_node)

        # 找出所有在这次循环清洗区里的节点（它们发出的信号都会失效）
        reset_sources = descendants | {start_node}

        for n in self.graph.nodes():
            if n in self.node_locks and "signals" in self.node_locks[n]:
                # 🛠️ 核心改造 2：大清洗时，只擦除由 reset_sources 发来的脏信号
                # 坚决保留从循环外部（比如之前的视觉寻图）传过来的历史记忆！
                new_signals = {}
                for signal_key, signal in self.node_locks[n]["signals"].items():
                    source_id = (
                        signal.get("source_id", signal_key)
                        if isinstance(signal, dict)
                        else signal_key
                    )
                    if source_id not in reset_sources:
                        new_signals[signal_key] = signal
                self.node_locks[n]["signals"] = new_signals

                if n in descendants:
                    bus.node_status_changed.emit(n, "Idle", "")

    @pyqtSlot(str, str, str)
    def _on_node_status_changed(self, node_id: str, status: str, result_str: str):
        if status in {
            "Success",
            "Skipped",
            "Failed",
            "Cancelled",
            "Jump_Triggered",
        }:
            self.active_nodes.discard(node_id)

        if status in {"Cancelled", "Jump_Triggered"}:
            self._cancel_execution()
            return

        if self.execution_failed:
            self._schedule_finish_check()
            return
        if status == "Success":
            import ast

            try:
                result_data = ast.literal_eval(result_str)
            except Exception:
                result_data = {}
            self.results_cache[node_id] = result_data

            if "active_ports" in result_data:
                active_ports = result_data.get("active_ports") or []
            else:
                active_ports = [result_data.get("active_port", "OUT")]
            if isinstance(active_ports, str):
                active_ports = [active_ports]
            active_ports = set(active_ports)
            source_signal_config = self.node_data_map.get(node_id, {}).get(
                "signal_config", {}
            )

            loop_target = None
            loop_envelope = None
            for u, v, edge_key, edge_data in self.graph.out_edges(
                node_id, keys=True, data=True
            ):
                src_port = edge_data.get("src_port")
                if src_port in active_ports and edge_data.get(
                    "is_feedback", False
                ):
                    envelope = build_signal_envelope(
                        node_id, src_port, result_data, source_signal_config
                    )
                    loop_target = v
                    loop_envelope = envelope
                    loop_signal_key = edge_data.get("signal_key", edge_key)
                    break

            if loop_target:
                # 触发回溯，绝对不向外溢出 Skipped
                self._resolve_dependency(
                    loop_target,
                    "Time_Loop",
                    src_node_id=node_id,
                    envelope=loop_envelope,
                    signal_key=loop_signal_key,
                )
            else:
                for u, v, edge_key, edge_data in self.graph.out_edges(
                    node_id, keys=True, data=True
                ):
                    src_port = edge_data.get("src_port")
                    is_feedback = edge_data.get("is_feedback", False)
                    signal_key = edge_data.get("signal_key", edge_key)

                    if src_port in active_ports:
                        if not is_feedback:
                            envelope = build_signal_envelope(
                                node_id,
                                src_port,
                                result_data,
                                source_signal_config,
                            )
                            self._resolve_dependency(
                                v,
                                "Trigger",
                                src_node_id=node_id,
                                envelope=envelope,
                                signal_key=signal_key,
                            )
                    else:
                        if not is_feedback:
                            self._resolve_dependency(
                                v,
                                "Skipped",
                                src_node_id=node_id,
                                signal_key=signal_key,
                            )

        elif status == "Skipped":
            for u, v, edge_key, edge_data in self.graph.out_edges(
                node_id, keys=True, data=True
            ):
                if not edge_data.get("is_feedback", False):
                    self._resolve_dependency(
                        v,
                        "Skipped",
                        src_node_id=node_id,
                        signal_key=edge_data.get("signal_key", edge_key),
                    )

        elif status == "Failed":
            self._abort_execution("节点执行失败，当前工作流已中断。", node_id)

        if status in {"Success", "Skipped", "Failed"}:
            self._schedule_finish_check()

    def _abort_execution(self, message, failed_node_id=None):
        if self.execution_failed:
            return
        self.execution_failed = True
        bus.log_emitted.emit("ERROR", "Engine", message)
        if failed_node_id:
            bus.node_status_changed.emit(failed_node_id, "Failed", "")
        self._schedule_finish_check()

    def _resolve_dependency(
        self,
        node_id: str,
        signal_type: str,
        src_node_id: str = "Engine_Root",
        envelope=None,
        signal_key=None,
    ):

        if self.execution_failed:
            return

        if signal_type in {"Trigger", "Time_Loop"}:
            target_signal_config = self.node_data_map.get(node_id, {}).get(
                "signal_config", {}
            )
            try:
                validate_receiver_input(envelope, target_signal_config)
            except SignalValidationError as exc:
                target_name = self.node_data_map.get(node_id, {}).get("name", node_id)
                self._abort_execution(
                    f"节点 [{target_name}] 输入校验失败：{exc}", node_id
                )
                return

        # 探针保留，方便观察
        target_name = self.node_data_map.get(node_id, {}).get("name", node_id[-4:])
        src_name = (
            self.node_data_map.get(src_node_id, {}).get("name", src_node_id[-4:])
            if src_node_id != "Engine_Root"
            else "Engine_Root"
        )

        type_suffix = ""
        if envelope:
            type_suffix = f" value:{value_type(envelope.get('value'))}"
        bus.log_emitted.emit(
            "WARN",
            "Probe",
            f"🎯 [{src_name}] --({signal_type}{type_suffix})--> [{target_name}]",
        )

        if signal_type == "Time_Loop":
            bus.log_emitted.emit(
                "SUCCESS", "Engine", "⏳ 触发时光回溯！重置下游时间线..."
            )
            self._reset_downstream(node_id)
            # 循环起点自己也要清空信号记忆，干干净净开始下一轮
            if node_id in self.node_locks:
                self.node_locks[node_id]["signals"].clear()
            self._dispatch_node(node_id, injected_signals=[envelope])
            return

        # 🛠️ 核心改造 3：把收到的信号按来源写入记忆字典
        if signal_type in ["Trigger", "Skipped"]:
            self.node_locks[node_id]["signals"][signal_key or src_node_id] = {
                "kind": signal_type,
                "source_id": src_node_id,
                "envelope": envelope,
            }

        locks = self.node_locks[node_id]

        # 只要收集齐了所有的进线信号（信号池大小等于 total）就开门结算
        if locks["total"] > 0 and len(locks["signals"]) == locks["total"]:
            triggered_count = sum(
                1
                for signal in locks["signals"].values()
                if (
                    signal.get("kind")
                    if isinstance(signal, dict)
                    else signal
                )
                == "Trigger"
            )
            skipped_count = sum(
                1
                for signal in locks["signals"].values()
                if (
                    signal.get("kind")
                    if isinstance(signal, dict)
                    else signal
                )
                == "Skipped"
            )

            # 隐式 OR 门：只有全军覆没才是 Skipped，只要有1个 Trigger 就执行
            if skipped_count > 0 and triggered_count == 0:
                bus.node_status_changed.emit(node_id, "Skipped", "{}")
            else:
                self._dispatch_node(node_id)
