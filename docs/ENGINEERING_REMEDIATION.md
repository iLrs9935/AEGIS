# AEGIS 工程整改交付

本文保留整改阶段的原始验证记录；正式 v3.0.1 的 175 项测试及中英 LLM 指南更新见 [发布复核](../RELEASE_REVIEW.md#v301-发布复核2026-11-14)。人工与详细实验记录正文按作者要求保留中文。

日期：2026-11-14。任务覆盖并发上下文、点击安全、执行权限和分层测试。
修改限定于本地工作目录；没有推送代码、触发云端任务或发布新版本。
原始源码检查点位于 `backups/engineering-20261114-121647`。

## 1. 上下文和并发

原始问题确实存在，但“全局字典”并非跨引擎的模块级单例：它原本在每次
`DAGEngine.start_execution()` 中创建。真正的竞争来自同一次运行的并发
Worker 共享该字典，包括 getter/setter 之外的数组出队、计时器、网络写入、
AI 格式化和嵌套 OK-WW 状态对象。另一个跨实例问题是全局 Qt 总线只携带
node_id，没有 run_id；同名节点、完成通知、图纸跳转可能影响其他引擎。

采用 `ExecutionContext`，每个引擎每次运行创建一个对象。短读写、快照和
提交由 RLock 保护；只存储内置数据类型，不把 Qt 对象或自定义回调放进锁内。
读写都复制嵌套列表/字典，杜绝取出对象后绕过保护修改共享数据。

| 访问路径 | 新的一致性规则 |
| --- | --- |
| func_logic getter/setter、network 直接写、系统证据读取 | Mapping 方法内部同步；返回独立副本 |
| AND/OR、多文本读取、提示词格式化 | 一次 snapshot，避免跨时刻混读 |
| iterator 弹出/更新剩余数组/写当前元素 | mutate 的纯数据变换，乐观版本比较后整体提交；冲突重算 |
| pulse_timer 首次初始化/超时删除 | 同一 mutate 中完成 |
| AI 追加回复 | mutate 追加并返回独立历史，数据库写入发生在锁外 |
| OK-WW 初始化/监控/清理、程序启动错误记录 | stateful/edit 保留对应状态键，使用本地副本，外部调用结束后提交；重叠状态操作明确失败 |
| 引擎调度 | 只允许所属 Qt 线程改动生命周期；同节点重入拒绝，保留原 Worker 的活动记录 |
| Worker 状态、完成、图纸跳转 | run_id 路由；公共旧信号保持显示/兼容用途，不能驱动其他运行的调度 |

普通同键赋值定义为最后提交者覆盖；计数、队列等需要“读改写”的操作必须
调用 mutate。纯 transform 可多次执行，不能放 I/O、日志或信号。edit 不在
I/O 期间持有互斥锁，其他键可以访问；相同状态键冲突时抛 ContextConflict，
不会默默丢失更新，也不会在外部副作用之后自动重试。

运行结束后 close 保留可读结果，拒绝旧 Worker 写入；下一次运行使用新对象。
clear 增加代数并使在途提交失效。引擎等待活动 Worker 全部退出才关闭上下文，
不靠提前清空字典取消操作。返回的列表/字典不再支持靠别名原地改写上下文：
这是有意收紧的内部 Python 扩展 API；JSON 节点数据传递格式不变。独立旧节点
调用仍接受调用者自己的 dict，但共享线程调用方应传 ExecutionContext。

新增确定性测试使用 Barrier/Event/Future：不同键并发、同键完整值读写、
原子增量与一致快照、并行出队、clear/close 竞态、键保留释放、外部回调访问、
真实 QThreadPool 多引擎同名节点、旧信号隔离、线程归属与同节点重入。

## 2. 点击模式

原始普通物理点击已有缺坐标检查；危险回退只在连续物理点击中真实存在。
两者均新增 `坐标模式`：`指定坐标` / `当前位置`，不把原有前台/后台
`执行模式` 混成同一个字段。未指定/未知模式返回 Failed；旧文件经显式迁移。

指定坐标必须是数值型有限整数像素（拒绝字符串、布尔、NaN、Infinity、
小数和缺失分量），位于 Windows 虚拟桌面矩形，支持负坐标多屏。
校验全部完成后才移动鼠标。后台模式还要求有效 HWND，不支持当前位置。
当前位置只有显式配置才启用，不读取缺失坐标来推断。点击按键/动作也校验。
连点次数限定 1–10000 整数、间隔 0–3600 秒；普通点击延迟 0–3600 秒。
已知输入错误直接给出 Failed/error；后端异常由 Worker 统一转换为 Failed。

旧图纸只在内存增加坐标模式与 click_mode_version=1，输出明确迁移警告，
不自动覆写原文件；保存后持久化。旧隐式原地连点必须手动选择当前位置。
本地兼容性扫描检查 19 个 JSON（公开示例、实际工作流、测试 fixture），均可
加载；共识别 19 个旧点击配置，原始文件哈希均未变化。没有执行私人工作流。
5 个公开示例由现有真实 Qt 加载测试检查节点/配置/连线，前三个真实引擎执行。

新增点击测试严格 Mock 所有鼠标移动与操作，涵盖缺 X/Y、类型、边界、多屏、
显式当前位置、未知/缺模式、后台限制、次数/间隔异常、后端失败恢复及迁移往返。

## 3. 权限边界

原始 --safe-power 只在休眠/终端退出 HAL 生效，不阻止通过启动解释器或键盘
触发相同系统效果；直接调用引擎原来没有统一授权入口。

完整 41 节点清单及实现依据见 [NODE_CAPABILITIES.md](NODE_CAPABILITIES.md)。
类别包括 read_only、desktop_interaction、file_modification、process_control、
system_control、external_service，以及额外的 workflow_execution。网页嗅探包含
Selenium 进程、网络与账本写入；可靠通知包含本地队列写入；视觉可能激活窗口；
对话保存写数据库；加载/卸载模型修改进程级原生资源。分类不只依据节点名称。

本地新建、外部文件、AI 来源均默认未授权。导入不能靠 trusted/permissions
字段自授信任；文件声明 AI 可保留来源，其余文件按 external 处理。本地新建
只描述来源，也不免授权。保存不保存执行授权。运行日志记录来源、run_id、
内容指纹及授予的能力，不记录完整配置或凭据。

执行前检查全部节点（包括未必走到的分支和反馈节点）、连接及未知类型。
UI 展示节点 ID、实际类型、影响和所需权限，点击显示坐标模式，擦除全部显示
特别说明，默认 No。拒绝时不启动任何节点。程序接口必须显式调用
`engine.authorize_execution(review.required)` 才能启动高风险运行；该调用本身
就是宿主代码作出的授权，不用于不可信 JSON。无授权直接调用 start_execution
或 NodeWorker 仍拒绝。

授权绑定来源、节点配置、信号配置、禁用状态和连接的内容指纹，配置在加载时
解析并复制。Worker 执行前再次检查授权及节点配置，运行中配置变化导致失败；
新一轮执行重新授权，嵌套目标不继承父权限。未知节点、重复 ID、断裂/不支持的
端口、异常元数据、非有限 JSON 数值在导入时拒绝，不再静默丢弃未知节点/连线。

--safe-power 现在定义为工作流只读能力模式：高风险能力一律拒绝，已有授权也
不能绕过；执行阶段再次检查标志。旧 HAL 仍直接屏蔽休眠/退出。它不是操作系统
沙箱：Python 扩展、本地原生库、资源消耗、应用自身初始化数据库/日志不在隔离
范围。外部启动的进程一旦被明确授权，AEGIS 不限制其子进程内部行为。

新增安全测试对全部风险节点、三类来源逐项验证拒绝与显式授权，覆盖直接 Worker、
配置/连接变化、队列等待期间开启只读模式、分支/反馈、嵌套权限、导入自授权、
UI 默认拒绝、跨实例完成/跳转。所有破坏性外部接口均使用替身。

## 4. 测试与发布

原始基线实际运行 125 项通过。新增 47 个测试方法，保留原测试及断言，仅将
依赖裸字典别名的测试改为提交写回/模拟时钟，并为原集成场景显式提供测试授权。
新增用例用 subTest 合并同类输入，方法数不把情景数重复累加。

| 验证 | 发现/实际执行 | 通过 | 失败/错误 | 跳过 |
| --- | ---: | ---: | ---: | ---: |
| 修改前 Python 3.14.4 | 125 / 125 | 125 | 0 / 0 | 0 |
| 修改后 Windows Python 3.12.8 | 172 / 172 | 172 | 0 / 0 | 0 |
| 修改后 Windows Python 3.13.12 | 172 / 172 | 172 | 0 / 0 | 0 |
| 修改后 Windows Python 3.14.4 | 172 / 172 | 172 | 0 / 0 | 0 |

同一套 172 方法，不将三个 Python 环境累加为 516 种测试。互斥分层为 unit 83、
integration 44、security 43、windows_runtime 2。重叠标签为 mock_assisted 132、
native_qt 46、windows_api 2；含义和保守统计规则见 [TESTING.md](TESTING.md)。
Windows 原生探针仍有 Mock 辅助，不可将 Mock 标签与原生标签相减推算纯实机数。
源码报告中的 packaged_exe_scenarios 为空；EXE 使用独立报告，不混入源码总数。

实际命令（标准环境需先安装 requirements.txt）：

```powershell
./release/validation-env/Scripts/python.exe -B scripts/run_tests.py --report release/remediation-tests-py314.json
./release/remediation-py312/Scripts/python.exe -B scripts/run_tests.py --report release/remediation-tests-py312.json
./release/remediation-py313/Scripts/python.exe -B scripts/run_tests.py --report release/remediation-tests-py313.json
./release/validation-env/Scripts/python.exe -B scripts/check_release.py
./release/validation-env/Scripts/python.exe -B scripts/build_portable.py --version 3.0.0 --output release/remediation-20261114
./release/validation-env/Scripts/python.exe -B scripts/verify_packaged.py --executable "release/remediation-20261114/dist/AEGIS Command Terminal/AEGIS Command Terminal.exe" --report release/remediation-packaged.json
```

各源码测试报告及同名 .log 位于忽略的 release/，包含逐测试 ID、环境及源码
Python 哈希。实际 EXE 验证仅在独立报告存在、场景通过且匹配 EXE SHA256 时
成立；构建成功不等于 EXE 验证成功。双语启动探针另行验证 Qt/ICU 与窗口。
旧 v3.0.0 的历史云端记录不作为本次整改代码的验证证据，也未被覆盖。

CI 保留隐私检查，补齐 Windows 3.12/3.13/3.14 全层运行及结果附件；发布任务
必须先通过同一源 SHA 的三版本测试，再构建并验证双语启动及四个 EXE 场景，
失败阻止原有草稿附件上传。尚未在 GitHub 运行这些更新后的 YAML。

实际 EXE 验证已完成：`release/remediation-packaged.json` 记录 4/4 场景通过；
双语原生窗口启动报告分别通过，包内 Qt/系统 ICU/工作流未改写检查通过。
EXE SHA256 为 `8b955419ddb235b77ce249d52d6e9cff7ea4183fb378d99ba3f241d0bccc79cf`。
免安装包 1,423 个载荷文件的清单逐项验证通过，加清单自身为 1,424 个文件。
其所有 Python 源码哈希与三版本报告一致。审计文档在验证后补记，免安装包
保留构建时文档快照；最终源码归档 `release/AEGIS-engineering-remediation-source.zip`
包含补记结果，Python 代码与构建输入一致。更新后的 CI YAML 已在本地解析，
并验证发布构建依赖三版本测试任务；未在云端运行。

## 修改文件

| 范围 | 文件 |
| --- | --- |
| 上下文/引擎/信号 | core/context.py（新增）、core/engine.py、core/event_bus.py、functions/func_logic.py |
| 上下文调用点 | nodes/logic.py、nodes/timers.py、nodes/ai.py、nodes/okww.py、nodes/system.py、nodes/text_ops.py；network 直接 Mapping 访问由上下文对象保护，无需改文件 |
| 点击/迁移 | nodes/actions.py、core/workflow.py（新增）、ui/translations.py |
| 权限/UI | core/security.py（新增）、nodes/__init__.py、ui/main_window.py、main.py |
| 测试 | tests/test_context_concurrency.py、test_click_safety.py、test_execution_security.py、test_node_contracts.py、test_test_reporting.py（均新增）；test_daily_runtime.py、test_okww_unattended.py（调整） |
| 报告与 EXE | scripts/run_tests.py、scripts/verify_packaged.py、core/package_probe.py（均新增） |
| CI | .github/workflows/ci.yml、.github/workflows/portable-release.yml |
| 文档 | readme.md、README.zh-CN.md、AI_WORKFLOW_PROMPT.md、SECURITY.md、RELEASE_REVIEW.md、docs/PORTABLE.md；docs/TESTING.md、docs/NODE_CAPABILITIES.md、本文（新增） |

## 已知限制与未验证项

- 自动化用例中的 Bark、OK-WW/游戏、键鼠、进程终止与休眠仍使用替身。用户已于
  2026-11-14 确认真实键鼠、Bark、OK-WW/游戏和实际休眠人工实测通过，见
  [人工验证记录](MANUAL_VALIDATION.md)。不将其计入自动化或绑定未提供的 EXE 哈希。
  Selenium 外站访问和单独的进程终止操作没有新增人工验证记录。
- 可选 llama 模型/DXCAM 没有实机验证。模型后端、SQLite、外部程序与全局急停
  属于进程/操作系统共享资源；上下文隔离不把它们变成各自独立的机器。
- 全局急停仍按现有架构作用于整个进程，不是每个 DAG 的独立暂停开关。
- OK-WW 同状态重入现在明确失败；需要把这些状态节点按顺序连接。保留键并不
  回滚已经发生的外部副作用，也不能取消操作系统中已经完成的输入/进程动作。
- 结束进程与置顶窗口的旧实现会吞掉部分底层异常并继续报告成功。基础测试明确
  记录该既有行为；本次未擅自改变其他节点的业务语义。授权成功不代表操作成功。
- 节点基础覆盖并非每个字段/每种硬件/远程服务故障的穷举；纯节点的外部依赖
  故障情景不适用。未来增加节点必须同时补齐分类、用例与真实运行验证范围。
- 当前目录无 Git 元数据，未生成提交/PR；构建是本地未发布候选，旧发布包未改。

## 人工验证与 LLM 文档补记（2026-11-14）

新增 [MANUAL_VALIDATION.md](MANUAL_VALIDATION.md) 记录用户确认通过的四类实际操作；新增 [LLM_WORKFLOW_QUICKSTART.md](LLM_WORKFLOW_QUICKSTART.md) 供模型快速构图，并在双语 README 和原生成提示词添加入口。原始自动化结果与二进制证据保留，Python 代码未改动。本轮补记后的源码另存为 `release/AEGIS-engineering-remediation-source-r2.zip`。
