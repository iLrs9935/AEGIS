# core/models.py
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class NodeStatus(str, Enum):
    """节点执行状态机"""

    IDLE = "Idle"
    WAITING = "Waiting"  # 并联/屏障等待中
    RUNNING = "Running"
    SUCCESS = "Success"
    FAILED = "Failed"


class PortModel(BaseModel):
    """端口模型（引脚）"""

    name: str = Field(..., description="端口名称，例如 'Image', 'Confidence'")
    type_hint: str = Field(
        default="Any", description="类型提示，用于 UI 连线时的类型检查拦截"
    )
    value: Any = Field(default=None, description="运行时携带的流转数据")


class NodeModel(BaseModel):
    """原子节点数据模型 (The Atom)"""

    id: str = Field(..., description="UUID 级别的唯一节点实例 ID")
    name: str = Field(..., description="节点类名，例如 'Find_Image'")
    category: str = Field(
        default="General", description="所属插件大类，如 'Vision', 'System'"
    )

    # 动态数据流 (Ports)
    inputs: Dict[str, PortModel] = Field(default_factory=dict)
    outputs: Dict[str, PortModel] = Field(default_factory=dict)

    # 静态配置参数 (例如寻图阈值、按键键码)，用于序列化保存
    config: Dict[str, Any] = Field(default_factory=dict)

    # 运行时状态 (不参与本地保存序列化)
    status: NodeStatus = Field(default=NodeStatus.IDLE)
    error_context: Optional[str] = None


class EdgeModel(BaseModel):
    """有向边模型 (连线)"""

    id: str = Field(..., description="边 UUID")
    source_node_id: str
    source_port_name: str
    target_node_id: str
    target_port_name: str


class DAGModel(BaseModel):
    """DAG 拓扑图完整视图 (大脑的蓝图)"""

    id: str = Field(default="main_dag")
    nodes: Dict[str, NodeModel] = Field(default_factory=dict)
    edges: List[EdgeModel] = Field(default_factory=list)
