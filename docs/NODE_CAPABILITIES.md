# 内置节点能力清单

2026-11-14：逐项检查注册函数及其 HAL 调用。与 `NODE_REGISTRY` 一一对应，共 41 种。

权限是可能发生效果的保守上界，与显示分类无关；如“系统休眠”的保留终端模式仍需 system_control。新节点未列入分类时禁止执行。read_only 允许运行实例内的数据更新、只读文件/日志/窗口/进程查询及本地推理，不代表没有 CPU/GPU 使用或应用自身初始化。

| 节点 | 实际实现 | 执行能力 | 审查依据 |
| --- | --- | --- | --- |
| Bark通知 | `nodes.notifications.bark_notification` | external_service | Bark 发送网络请求；可靠通知还写/刷新离线队列。 |
| OK-WW任务监控 | `nodes.okww.monitor_okww_task` | read_only | 初始化/监控读取日志和进程快照并更新上下文；安全清理结束已归属的进程。 |
| OK-WW安全清理 | `nodes.okww.cleanup_okww_session` | process_control | 初始化/监控读取日志和进程快照并更新上下文；安全清理结束已归属的进程。 |
| OK-WW监控初始化 | `nodes.okww.initialise_okww_monitor` | read_only | 初始化/监控读取日志和进程快照并更新上下文；安全清理结束已归属的进程。 |
| 信号中继器 | `nodes.logic.signal_relay` | read_only | 仅变换运行时数据/上下文和选择输出分支。 |
| 信号分流器 | `nodes.logic.signal_router_node` | read_only | 仅变换运行时数据/上下文和选择输出分支。 |
| 信号暂存器 | `nodes.logic.signal_buffer` | read_only | 仅变换运行时数据/上下文和选择输出分支。 |
| 写入记忆 | `nodes.memory.memory_write_node` | file_modification | 读取持久化 SQLite 或写入/擦除数据库，按实际函数分别分类。 |
| 删除记忆 | `nodes.memory.memory_delete_node` | file_modification | 读取持久化 SQLite 或写入/擦除数据库，按实际函数分别分类。 |
| 加载大模型 | `nodes.ai.node_load_llm` | system_control | 提示词/历史读取/推理仅处理本地数据；对话保存写 SQLite；加载/卸载修改进程级原生模型与显存资源。 |
| 加载并组装对话 | `nodes.ai.node_load_chat` | read_only | 提示词/历史读取/推理仅处理本地数据；对话保存写 SQLite；加载/卸载修改进程级原生模型与显存资源。 |
| 动态变量粘贴 | `nodes.actions.dynamic_paste_action` | desktop_interaction | 调用鼠标、键盘或剪贴板 HAL；动态粘贴也会查找/激活窗口。 |
| 卸载大模型 | `nodes.ai.node_unload_llm` | system_control | 提示词/历史读取/推理仅处理本地数据；对话保存写 SQLite；加载/卸载修改进程级原生模型与显存资源。 |
| 可靠Bark通知 | `nodes.notifications.reliable_bark_notification` | external_service, file_modification | Bark 发送网络请求；可靠通知还写/刷新离线队列。 |
| 启动程序 | `nodes.system.start_program` | process_control | 按函数分别调用启动/结束进程、窗口激活、电源/退出或跳转总线。 |
| 唤醒并置顶窗口 | `nodes.system.activate_target_window` | desktop_interaction | 按函数分别调用启动/结束进程、窗口激活、电源/退出或跳转总线。 |
| 多文本合并 | `nodes.text_ops.node_text_merge` | read_only | 仅变换运行时文本/上下文和更新本节点显示。 |
| 大模型推理 | `nodes.ai.node_llm_inference` | read_only | 提示词/历史读取/推理仅处理本地数据；对话保存写 SQLite；加载/卸载修改进程级原生模型与显存资源。 |
| 强制粘贴 | `nodes.actions.paste_text` | desktop_interaction | 调用鼠标、键盘或剪贴板 HAL；动态粘贴也会查找/激活窗口。 |
| 持续滚轮 | `nodes.actions.mouse_wheel_action` | desktop_interaction | 调用鼠标、键盘或剪贴板 HAL；动态粘贴也会查找/激活窗口。 |
| 数组遍历器 | `nodes.logic.logic_iterator_node` | read_only | 仅变换运行时数据/上下文和选择输出分支。 |
| 文本展示 | `nodes.text_ops.node_simple_text_show` | read_only | 仅变换运行时文本/上下文和更新本节点显示。 |
| 文本输入 | `nodes.text_ops.node_simple_text_input` | read_only | 仅变换运行时文本/上下文和更新本节点显示。 |
| 构建提示词 | `nodes.ai.node_build_prompt` | read_only | 提示词/历史读取/推理仅处理本地数据；对话保存写 SQLite；加载/卸载修改进程级原生模型与显存资源。 |
| 物理点击 | `nodes.actions.click_target` | desktop_interaction | 调用鼠标、键盘或剪贴板 HAL；动态粘贴也会查找/激活窗口。 |
| 状态检测 | `nodes.triggers.check_program_status` | read_only | 仅检查窗口/进程存在，返回句柄和状态。 |
| 等待时间 | `nodes.timers.wait_node` | read_only | 仅等待与维护运行时计时状态。 |
| 系统休眠 | `nodes.system.s4_hibernate_and_exit` | system_control | 按函数分别调用启动/结束进程、窗口激活、电源/退出或跳转总线。 |
| 结束进程 | `nodes.system.close_program` | process_control | 按函数分别调用启动/结束进程、窗口激活、电源/退出或跳转总线。 |
| 脉冲计时器 | `nodes.timers.pulse_timer` | read_only | 仅等待与维护运行时计时状态。 |
| 视觉寻图 | `nodes.vision.find_target_image` | desktop_interaction | 前台模式会激活窗口；即使后台配置也保守保留桌面权限。 |
| 记录兑换码结果 | `nodes.network.record_redeem_result` | file_modification | 网页嗅探启动 Selenium、访问网络并更新账本；兑换结果只写账本。 |
| 读取记忆 | `nodes.memory.memory_read_node` | read_only | 读取持久化 SQLite 或写入/擦除数据库，按实际函数分别分类。 |
| 运行新图纸 | `nodes.system.execute_blueprint_jump` | workflow_execution | 按函数分别调用启动/结束进程、窗口激活、电源/退出或跳转总线。 |
| 连续物理点击 | `nodes.actions.rapid_click_target` | desktop_interaction | 调用鼠标、键盘或剪贴板 HAL；动态粘贴也会查找/激活窗口。 |
| 追加并保存对话 | `nodes.ai.node_save_chat` | file_modification | 提示词/历史读取/推理仅处理本地数据；对话保存写 SQLite；加载/卸载修改进程级原生模型与显存资源。 |
| 通用网页嗅探 | `nodes.network.fetch_web_data` | external_service, file_modification, process_control | 网页嗅探启动 Selenium、访问网络并更新账本；兑换结果只写账本。 |
| 逻辑与门 | `nodes.logic.logic_and_node` | read_only | 仅变换运行时数据/上下文和选择输出分支。 |
| 逻辑或门 | `nodes.logic.logic_or_node` | read_only | 仅变换运行时数据/上下文和选择输出分支。 |
| 逻辑非门 | `nodes.logic.logic_not_node` | read_only | 仅变换运行时数据/上下文和选择输出分支。 |
| 键盘操作 | `nodes.actions.keyboard_action` | desktop_interaction | 调用鼠标、键盘或剪贴板 HAL；动态粘贴也会查找/激活窗口。 |

所有类型的基础正常输出、缺失输入、缺失配置和输入容器校验见 `tests/test_node_contracts.py` 中独立编写的 `CASES`；权限拒绝/授权、来源和只读模式覆盖见 `tests/test_execution_security.py`。这两处都断言清单与注册表完全一致，新增类型必须更新行为用例和能力清单。

底层外部操作均有替身，不能将这些节点的测试通过解释成真实服务/键鼠/进程/电源操作成功。更深层覆盖：点击见 `test_click_safety.py`，上下文/并行见 `test_context_concurrency.py`，反馈循环/数据传递见公开示例引擎测试，后台键盘见 `test_background_keyboard.py`，OK-WW/可靠通知见 `test_okww_unattended.py` 和 `test_daily_recovery.py`，电源见 `test_system_power_actions.py`。
