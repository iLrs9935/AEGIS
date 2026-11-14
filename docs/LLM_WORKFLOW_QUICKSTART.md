# AEGIS：给 LLM 的 Workflow 构筑速成

**简体中文** · [English](LLM_WORKFLOW_QUICKSTART.en.md) · 适用于 AEGIS v3.0.1

把本文件交给 LLM，再附上需求，即可开始生成图纸。以下以当前源码为准；英文界面仍使用相同中文内部标识。这里只教构图；完整参数先查 `nodes/*.py` 注册 schema，旧版详细目录见 [AI_WORKFLOW_PROMPT.md](../AI_WORKFLOW_PROMPT.md)。OK-WW 任务优先修改 [现成监控示例](../examples/workflows/05_okww_supervision.json)，不要凭名称重建它的恢复与清理逻辑。

## 直接给模型的任务约定

你是 AEGIS 工作流构筑助手。根据用户需求生成可加载的 UTF-8 JSON。最终回复只含一个 JSON 对象，不要代码围栏、注释、省略号或解释。

1. 顶层固定为 `meta`、`nodes`、`groups`、`edges`。`meta` 使用 `{"theme":"Command Terminal","edge_style":"curve","source":"ai","click_mode_version":1}`；无分组则 `groups: []`。
2. 节点 `id` 全图唯一，`type` 使用真实注册类型，`name` 只是显示名称。不要把英文翻译、显示名或自创“并行/结束/条件”节点填入 `type`。
3. 按下文完整模板填写节点外观字段。每列 x 加 280，同列分支 y 至少相差 150；保持 `w:190,h:84,_expanded_height:84,display_mode:"standard"`。
4. 所有边都是 `{"src_id":"来源ID","src_port":"真实出口","tgt_id":"目标ID","tgt_port":"IN"}`。出口名称逐字匹配；分流器出口来自 `路由规则[].port`，不能擅用 `OUT`。
5. `config` 中普通数字通常写字符串，枚举选一项，不要把 schema 的枚举数组整段填进去；`路由规则` 等结构化配置例外，保留数组/对象。`$FILE$`、`$TEXTAREA$` 是控件标记，要替换为实际路径/文本。
6. 不猜测密钥。Bark 地址写 `${ENV:AEGIS_BARK_URL}`，由用户在本机配置。未知路径用明确占位文本；不要把占位值宣称为已经能执行。
7. 高风险工作流须经用户逐次审查授权，JSON 不携带可生效的 `trusted` / `permissions`。`--autorun` 不授予权限，`--safe-power` 会拒绝高风险能力；跳转的目标图纸重新审查。
8. 默认生成无环图。仅在明确需要遍历/重试时增加反馈线，并设置耗尽、尝试次数或超时出口。不要让同一个节点实例在尚未结束时重入。

## 数据怎样传：只记住一个 value

每条边只携带一个业务 `value`，可为 boolean、number、string、object、array 或 null。执行状态 Success/Failed/Skipped 不属于第二份业务数据。

- `signal_config.outputs.<出口>.value: ""` 表示使用节点实际输出，不表示强制输出空字符串。
- 要输出常量，写“常量文本”：`"false"` 解析为布尔 false，`"0"` 为数字 0，`"[1,2]"` 为数组。若要业务字符串 `false`，覆盖文本需是带 JSON 引号的 `"\"false\""`。
- `input.type` 仅可为 `any/boolean/number/string/object/array/null`。`required:true` 拒绝缺失或 null；布尔 false、数字 0、空字符串仍是有效业务值。
- 多条正向进线会等待每条均触发或跳过；至少一条触发才运行，全部跳过则跳过。不是任意进线先到就立刻运行。
- 有明确上游数据的节点用连线传 value；兼容变量通过节点自带配置读写。**并非所有节点都会自动读取或原样转发 value**：例如“文本输入/多文本合并/文本展示”主要通过变量名共享文本；需要传递指定 value 时核查实现或设置出口覆盖文本。
- 上下文仅在本次运行中共享，下一次运行重新创建；跨运行持久化使用记忆/账本节点。并行写同一变量时最后提交者覆盖，尽量分配独立变量名，汇合后再消费。

## 从无副作用的完整图纸开始

这份 JSON 可直接加载并执行：把文本存为 `greeting`，再由展示节点读取同名变量。

```json
{
  "meta": {"theme":"Command Terminal","edge_style":"curve","source":"ai","click_mode_version":1},
  "nodes": [
    {
      "id":"text","type":"文本输入","name":"写入问候","category":"文本",
      "display_mode":"standard","x":0,"y":0,"w":190,"h":84,"_expanded_height":84,
      "config":{"节点标签":"问候","文本内容":"你好，AEGIS！","存入变量名":"greeting"},
      "signal_config":{"outputs":{"文本输出":{"value":""}},"input":{"type":"any","required":false}},
      "is_disabled":false,"is_collapsed":false
    },
    {
      "id":"show","type":"文本展示","name":"显示问候","category":"文本",
      "display_mode":"standard","x":280,"y":0,"w":190,"h":84,"_expanded_height":84,
      "config":{"节点标签":"结果","读取变量名":"greeting","展示内容":""},
      "signal_config":{"outputs":{"通过":{"value":""}},"input":{"type":"any","required":false}},
      "is_disabled":false,"is_collapsed":false
    }
  ],
  "groups": [],
  "edges": [{"src_id":"text","src_port":"文本输出","tgt_id":"show","tgt_port":"IN"}]
}
```

## 最常用的“找到才点击”完整图纸

必须是 `视觉寻图.OUT → 信号分流器 → 找到目标 → 物理点击`。寻图本身只有 `OUT`，结果对象的 `found` 决定分支；分流器保留整个对象，点击才能收到 `target_x/target_y/hwnd`。未找到出口可以不接，绝不能也连到点击。先填写窗口标题和图片路径，再由用户审查执行。

```json
{
  "meta": {"theme":"Command Terminal","edge_style":"curve","source":"ai","click_mode_version":1},
  "nodes": [
    {
      "id":"find","type":"视觉寻图","name":"寻找目标按钮","category":"视觉",
      "display_mode":"standard","x":0,"y":0,"w":190,"h":84,"_expanded_height":84,
      "config":{"执行模式":"后台(静默寻图)","节点标签":"寻找按钮","窗口标题":"请填写窗口标题","图片路径":"C:/请填写/button.png","置信度":"0.8","灰度匹配":"是","匹配策略":"最高置信度","目标序号(第几个)":"1","重试次数":"3","重试间隔(s)":"1"},
      "signal_config":{"outputs":{"OUT":{"value":""}},"input":{"type":"any","required":false}},
      "is_disabled":false,"is_collapsed":false
    },
    {
      "id":"route","type":"信号分流器","name":"仅允许找到目标","category":"逻辑",
      "display_mode":"standard","x":280,"y":0,"w":190,"h":84,"_expanded_height":84,
      "config":{"节点标签":"检查 found","输入选择":"最后一个","匹配模式":"首个匹配","路由规则":[{"port":"找到目标","path":"found","operator":"等于","target":"true"},{"port":"未找到","path":"found","operator":"等于","target":"false"}],"未匹配时":"终止工作流","默认出口名称":"默认"},
      "signal_config":{"outputs":{"找到目标":{"value":""},"未找到":{"value":""}},"input":{"type":"object","required":true}},
      "is_disabled":false,"is_collapsed":false
    },
    {
      "id":"click","type":"物理点击","name":"点击找到的位置","category":"动作",
      "display_mode":"standard","x":560,"y":0,"w":190,"h":84,"_expanded_height":84,
      "config":{"坐标模式":"指定坐标","执行模式":"前台物理(真实鼠标)","点击按键":"left","点击动作":"单击","操作前延迟(s)":"0.1"},
      "signal_config":{"outputs":{"OUT":{"value":""}},"input":{"type":"object","required":true}},
      "is_disabled":false,"is_collapsed":false
    }
  ],
  "groups": [],
  "edges": [
    {"src_id":"find","src_port":"OUT","tgt_id":"route","tgt_port":"IN"},
    {"src_id":"route","src_port":"找到目标","tgt_id":"click","tgt_port":"IN"}
  ]
}
```

点击规则：两种点击节点都必须写 `坐标模式`，通常为 `指定坐标`。X/Y 必须是 Windows 虚拟桌面内的数值型有限整数像素；缺任一坐标就失败。只有用户明确要求原地点击，才写 `当前位置`，且此模式仅用于前台。不要通过缺坐标触发当前位置模式。连续点击次数为 1–10000 的整数，间隔为 0–3600 秒有限值。

## 用这些配方扩展

| 需求 | 接法与关键配置 |
| --- | --- |
| 等待 | `等待时间`：`等待时长(s):"1"`，出口 `OUT`；无需发明 Delay 节点 |
| 判断 value | `信号分流器`：`path:""` 比较整个 value，`path:"found"` 比较对象字段；target 是文本，`"true"` 代表布尔值 |
| 复杂分支 | operator 仅可用 等于、不等于、包含、大于、大于等于、小于、小于等于、存在、不存在；首个匹配默认安全，没有命中则终止，明确需要才设置默认出口 |
| 多路并行 | 一个出口接多个下游；各下游使用不同节点 ID。条件分支不需要执行的路径由引擎传播 Skipped |
| 遍历数组 | 数组 value → `数组遍历器`；`弹出元素(继续)` → 处理节点 → 反馈至遍历器；`队列为空(完成)` → 收尾。反馈传处理结果/单元素，不要再传整个初始数组。参考公开示例 03 |
| 发送通知 | `Bark通知`，分类 `通知`，出口 `OUT`；配置 `Bark推送地址/通知标题/通知内容`。需重试/落盘队列时用 `可靠Bark通知`，分类 `OK-WW`，照公开示例 04 的配置 |
| 启动程序 | `启动程序`，分类 `系统`，出口 `OUT`；配置 `程序路径/启动参数/等待启动(s)`。工作目录等额外字段查源码 schema，不把 PowerShell 文本当文件路径 |
| 键盘输入 | `键盘操作`，分类 `动作`，出口 `OUT`；字段是 `按键名(如 F/SPACE/ENTER) 或 文本`；后台模式用 `输入方式:"后台消息(PostMessage)"` 和 `目标窗口标题(后台消息)` |
| 粘贴动态文本 | 字符串 value → `动态变量粘贴`，出口 `已粘贴`；兼容变量字段 `读取变量名`。不要把“强制粘贴”的 `粘贴文本` 配置当作自动绑定上游 value |
| 检查程序 | `状态检测`，分类 `触发`；配置 `检测模式/目标名称`，出口 `已运行/未运行`，存在时可带 hwnd |
| OK-WW 无人值守 | 复制公开示例 05，按本机路径修改初始化/日志配置。监控初始化 → 启动 → 日志监控 → 分支 → 归属清理；没有本次成功和清理证据，不接休眠 |
| 电源收尾 | `系统休眠` 的 `执行动作` 必须明确指定。默认构图用 `保留终端(不休眠)`；仅在用户要求休眠时改为 `S4休眠并退出终端`，并设置 `执行前倒计时(s)`；OK-WW 使用 `休眠前校验:"本次OK-WW成功且清理完成"` |

## 下笔前与输出前自检

1. 先列出步骤、每步输入来源、输出端口、失败/未找到分支和循环退出条件，再生成 JSON。
2. 不直接用“视觉寻图”的旧版 `找到目标/未找到` 出口，新图纸使用分流器。
3. `outputs` 覆盖真实出口；分流器的输出名称与规则一致；所有边引用现有节点，目标端口固定 `IN`。
4. 不把下游改成 `required:false` 来掩盖丢失坐标或数据；不把正常 false 当失败；不覆盖寻图/通知的原生对象导致坐标/状态丢失。
5. 不把节点状态 Success 或任意常量 `{"state":"success"}` 当作 OK-WW 成功/清理凭证；电源节点读取本次内部证据。
6. 核查路径、窗口标题、凭据引用、坐标模式、循环上限、授权和所有占位值。
7. 无副作用示例可在授权范围内执行；含键鼠、通知、进程或电源的图纸先加载审查。导入成功不代表实际操作验证通过。

源码可用时的只读结构校验（**不执行工作流**）：

```python
import json
from pathlib import Path
from core.workflow import validate_document
from nodes import NODE_REGISTRY

data = json.loads(Path("workflow.json").read_text(encoding="utf-8-sig"))
validate_document(data, NODE_REGISTRY)
```

这只检查结构、类型标识、端口引用等基础约束，不证明图片/路径存在、业务流程正确或外部服务可用。导入节点模块也可能初始化应用自身资源。完整图纸参考：01 文本、02 对象分流、03 数组反馈、04 可靠 Bark、05 OK-WW，均位于 `examples/workflows/`。
