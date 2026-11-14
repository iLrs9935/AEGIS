# AEGIS: LLM workflow quickstart

**English** · [简体中文](LLM_WORKFLOW_QUICKSTART.md) · AEGIS v3.0.1

Give this file to an LLM together with the task you want to automate. The English UI uses the same canonical Chinese type names, configuration keys, enum values and port identifiers in JSON. Translate display names and user text if desired; keep serialized identifiers exactly as shown. For complete current parameters, inspect the registration schemas in `nodes/*.py`. The older [detailed generation prompt](../AI_WORKFLOW_PROMPT.md) provides additional examples. For OK-WW, adapt the [existing supervision workflow](../examples/workflows/05_okww_supervision.json) rather than reconstructing its recovery and cleanup logic from node names.

## Instructions to the model

You are an AEGIS workflow builder. Turn the user's requirements into a loadable UTF-8 JSON workflow. Your final answer must contain one JSON object only: no Markdown fences, comments, ellipses or explanations.

1. Use the top-level fields `meta`, `nodes`, `groups` and `edges`. Set `meta` to `{"theme":"Command Terminal","edge_style":"curve","source":"ai","click_mode_version":1}`. Use `groups: []` unless grouping is required.
2. Every node needs a unique `id`. `type` selects a registered function; `name` is a display label. Do not substitute English UI labels or invent Parallel, End or Condition node types.
3. Follow the complete appearance fields in the examples. Place columns 280 pixels apart and branch rows at least 150 pixels apart. Standard nodes use `w:190,h:84,_expanded_height:84,display_mode:"standard"`.
4. Edges have exactly this shape: `{"src_id":"source-id","src_port":"real-output-port","tgt_id":"target-id","tgt_port":"IN"}`. Match ports exactly. Router output ports come from `路由规则[].port`, not a generic `OUT`.
5. Ordinary numeric configuration values are generally strings. Select one enum value instead of copying the schema's whole choice array. Structured fields such as `路由规则` remain arrays/objects. Replace `$FILE$` and `$TEXTAREA$` UI markers with actual paths/text.
6. Never invent or expose secrets. Use `${ENV:AEGIS_BARK_URL}` for the Bark URL and let the user configure it locally. Mark unknown paths with clear placeholders; do not claim placeholder configurations are ready to execute.
7. Workflows with effects require explicit per-run review. JSON cannot grant itself trust or permissions. `--autorun` grants nothing; `--safe-power` rejects high-risk capabilities. A nested workflow needs its own review.
8. Generate an acyclic graph by default. Add feedback only for an explicitly requested loop/retry, with an exhaustion, attempt-limit or timeout exit. Do not reenter the same node instance while it is still executing.

## Data flow: one value per edge

Each edge carries one business `value`: boolean, number, string, object, array or null. Success/Failed/Skipped are scheduler states, not a second business payload.

- `signal_config.outputs.<port>.value: ""` means use the node's actual result; it does not force an empty-string payload.
- To override with a constant, use constant text: `"false"` parses as boolean false, `"0"` as numeric zero, and `"[1,2]"` as an array. For the business string `false`, the override text must include JSON quotation marks: `"\"false\""`.
- `input.type` accepts only `any/boolean/number/string/object/array/null`. `required:true` rejects missing/null input. Boolean false, numeric zero and an empty string are valid business values.
- A join waits for every forward incoming edge to trigger or be skipped. At least one trigger runs the node; all skipped inputs skip it. It does not run immediately when the first input arrives.
- Prefer connected values when a node supports them. **Not every node automatically consumes or forwards the incoming value.** For example, `文本输入`, `多文本合并` and `文本展示` primarily share text through configured context-variable names. Check the function or set an explicit output override when needed.
- Context belongs to one run and is recreated for the next. Use memory/ledger nodes for persistence. Concurrent plain writes to the same variable are last-commit-wins; use distinct variable names and consume them after a join.

## A complete workflow without external actions

This workflow stores a greeting in `greeting`, then reads that same context variable for display. It can be loaded and executed directly.

```json
{
  "meta": {
    "theme": "Command Terminal",
    "edge_style": "curve",
    "source": "ai",
    "click_mode_version": 1
  },
  "nodes": [
    {
      "id": "text",
      "type": "文本输入",
      "name": "Write greeting",
      "category": "文本",
      "display_mode": "standard",
      "x": 0,
      "y": 0,
      "w": 190,
      "h": 84,
      "_expanded_height": 84,
      "config": {
        "节点标签": "Write greeting",
        "文本内容": "Hello, AEGIS!",
        "存入变量名": "greeting"
      },
      "signal_config": {
        "outputs": {
          "文本输出": {
            "value": ""
          }
        },
        "input": {
          "type": "any",
          "required": false
        }
      },
      "is_disabled": false,
      "is_collapsed": false
    },
    {
      "id": "show",
      "type": "文本展示",
      "name": "Show greeting",
      "category": "文本",
      "display_mode": "standard",
      "x": 280,
      "y": 0,
      "w": 190,
      "h": 84,
      "_expanded_height": 84,
      "config": {
        "节点标签": "Show greeting",
        "读取变量名": "greeting",
        "展示内容": ""
      },
      "signal_config": {
        "outputs": {
          "通过": {
            "value": ""
          }
        },
        "input": {
          "type": "any",
          "required": false
        }
      },
      "is_disabled": false,
      "is_collapsed": false
    }
  ],
  "groups": [],
  "edges": [
    {
      "src_id": "text",
      "src_port": "文本输出",
      "tgt_id": "show",
      "tgt_port": "IN"
    }
  ]
}
```

## A complete find-then-click workflow

Use `视觉寻图.OUT → 信号分流器 → 找到目标 → 物理点击`. Vision emits only `OUT`; its result object's `found` field selects the branch. The router preserves the complete object, including `target_x`, `target_y` and `hwnd` needed by the click node. The not-found port may remain unconnected; never connect it to the click. Fill in the window title and image path, then obtain the user's execution approval.

```json
{
  "meta": {
    "theme": "Command Terminal",
    "edge_style": "curve",
    "source": "ai",
    "click_mode_version": 1
  },
  "nodes": [
    {
      "id": "find",
      "type": "视觉寻图",
      "name": "Find target button",
      "category": "视觉",
      "display_mode": "standard",
      "x": 0,
      "y": 0,
      "w": 190,
      "h": 84,
      "_expanded_height": 84,
      "config": {
        "执行模式": "后台(静默寻图)",
        "节点标签": "Find target button",
        "窗口标题": "PLEASE_SET_WINDOW_TITLE",
        "图片路径": "C:/PLEASE_SET/button.png",
        "置信度": "0.8",
        "灰度匹配": "是",
        "匹配策略": "最高置信度",
        "目标序号(第几个)": "1",
        "重试次数": "3",
        "重试间隔(s)": "1"
      },
      "signal_config": {
        "outputs": {
          "OUT": {
            "value": ""
          }
        },
        "input": {
          "type": "any",
          "required": false
        }
      },
      "is_disabled": false,
      "is_collapsed": false
    },
    {
      "id": "route",
      "type": "信号分流器",
      "name": "Continue only when found",
      "category": "逻辑",
      "display_mode": "standard",
      "x": 280,
      "y": 0,
      "w": 190,
      "h": 84,
      "_expanded_height": 84,
      "config": {
        "节点标签": "Continue only when found",
        "输入选择": "最后一个",
        "匹配模式": "首个匹配",
        "路由规则": [
          {
            "port": "找到目标",
            "path": "found",
            "operator": "等于",
            "target": "true"
          },
          {
            "port": "未找到",
            "path": "found",
            "operator": "等于",
            "target": "false"
          }
        ],
        "未匹配时": "终止工作流",
        "默认出口名称": "默认"
      },
      "signal_config": {
        "outputs": {
          "找到目标": {
            "value": ""
          },
          "未找到": {
            "value": ""
          }
        },
        "input": {
          "type": "object",
          "required": true
        }
      },
      "is_disabled": false,
      "is_collapsed": false
    },
    {
      "id": "click",
      "type": "物理点击",
      "name": "Click detected location",
      "category": "动作",
      "display_mode": "standard",
      "x": 560,
      "y": 0,
      "w": 190,
      "h": 84,
      "_expanded_height": 84,
      "config": {
        "坐标模式": "指定坐标",
        "执行模式": "前台物理(真实鼠标)",
        "点击按键": "left",
        "点击动作": "单击",
        "操作前延迟(s)": "0.1"
      },
      "signal_config": {
        "outputs": {
          "OUT": {
            "value": ""
          }
        },
        "input": {
          "type": "object",
          "required": true
        }
      },
      "is_disabled": false,
      "is_collapsed": false
    }
  ],
  "groups": [],
  "edges": [
    {
      "src_id": "find",
      "src_port": "OUT",
      "tgt_id": "route",
      "tgt_port": "IN"
    },
    {
      "src_id": "route",
      "src_port": "找到目标",
      "tgt_id": "click",
      "tgt_port": "IN"
    }
  ]
}
```

Both click types require an explicit `坐标模式`. Normally use `指定坐标` (specified coordinates). X/Y must be finite integer-valued numeric pixels inside the Windows virtual desktop; either missing coordinate fails. Only use `当前位置` (current position) when the user explicitly requests it, and only for foreground clicks. Missing coordinates must never imply this mode. Rapid clicking accepts an integer count of 1–10000 and a finite interval of 0–3600 seconds.

## Recipes to extend the examples

| Requirement | Wiring and canonical configuration |
| --- | --- |
| Wait | `等待时间`, category `时间`, output `OUT`; `等待时长(s):"1"`. Do not invent a Delay type. |
| Test a value | `信号分流器`, category `逻辑`: empty `path` compares the entire value; `path:"found"` reads an object field. `target:"true"` is text parsed into a boolean. |
| More conditions | Operators: `等于`, `不等于`, `包含`, `大于`, `大于等于`, `小于`, `小于等于`, `存在`, `不存在`. Default to `首个匹配`. No match terminates unless an explicit default output is configured. |
| Parallel branches | Connect one output to multiple downstream node instances with distinct IDs. Inactive conditional paths propagate Skipped through the engine. |
| Array iteration | Array value → `数组遍历器`; output `弹出元素(继续)` → item processing → feedback to iterator. Output `队列为空(完成)` → finalization. Feedback carries an item/result, not the entire original array. See public example 03. |
| Notifications | `Bark通知`, category `通知`, output `OUT`; fields `Bark推送地址/通知标题/通知内容`. For retry/outbox behavior use `可靠Bark通知`, category `OK-WW`, following public example 04. |
| Start a program | `启动程序`, category `系统`, output `OUT`; fields `程序路径/启动参数/等待启动(s)`. Inspect the schema for working-directory options. A shell command is not an executable file path. |
| Keyboard input | `键盘操作`, category `动作`, output `OUT`. The target key/text field is `按键名(如 F/SPACE/ENTER) 或 文本`. Background mode uses `输入方式:"后台消息(PostMessage)"` and `目标窗口标题(后台消息)`. |
| Paste dynamic text | String value → `动态变量粘贴`, output `已粘贴`; compatibility variable field `读取变量名`. The `粘贴文本` field of `强制粘贴` does not automatically bind the incoming value. |
| Inspect a program | `状态检测`, category `触发`; fields `检测模式/目标名称`, outputs `已运行/未运行`; may include hwnd when found. |
| Unattended OK-WW | Adapt public example 05 and local executable/log paths. Initialize → launch → inspect logs → branch → owned-process cleanup. Do not request hibernation without this run's success and cleanup evidence. |
| Power finalization | Explicitly configure `系统休眠.执行动作`. Default generated workflows to `保留终端(不休眠)` (keep terminal, no hibernation). Only select `S4休眠并退出终端` when requested, and set `执行前倒计时(s)`. For OK-WW use `休眠前校验:"本次OK-WW成功且清理完成"`. |

## Checklist before producing the final JSON

1. Plan each step's input source, real output ports, failure/not-found branch and loop exit before writing JSON.
2. Do not emit legacy vision `找到目标/未找到` output ports; use a router after `视觉寻图.OUT`.
3. Cover real output ports in `signal_config.outputs`; match router ports to its rules. Every edge references existing IDs and targets `IN`.
4. Do not weaken `required` to hide missing coordinates/data. Do not interpret false as failure. Do not overwrite vision/notification result objects and thereby discard coordinates or status.
5. Scheduler Success and arbitrary constants such as `{"state":"success"}` are not OK-WW success/cleanup proof. The power node checks this run's internal evidence.
6. Check paths, window titles, credential references, coordinate mode, loop bounds, permissions and all placeholders.
7. Execute effect-free examples within the user's authorization. Review workflows containing input, notifications, process or power actions before running them. Import success is not evidence of successful real operations.

When source is available, this checks document structure **without executing the workflow**:

```python
import json
from pathlib import Path
from core.workflow import validate_document
from nodes import NODE_REGISTRY

data = json.loads(Path("workflow.json").read_text(encoding="utf-8-sig"))
validate_document(data, NODE_REGISTRY)
```

This checks basic structure, canonical types and port references, not file existence, business correctness or remote-service availability. Importing node modules can initialize application-owned resources. Public examples under `examples/workflows/` cover 01 text, 02 object routing, 03 array feedback, 04 reliable Bark and 05 OK-WW. Detailed manual and engineering validation records remain in Chinese.
