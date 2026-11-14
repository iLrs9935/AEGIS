# GitHub 发布前代码审阅

日期：2026-11-13；发布复核：2026-11-14。结论：已发布经过白名单和隐私检查的公开源码，本地私有数据保留在原工作目录中。

## 已修复的问题

| 级别 | 发现 | 处理 |
| --- | --- | --- |
| 高 | 私人每日工作流内嵌真实 Bark 设备地址 | 迁移至被忽略的 `config.local.json`，原工作流改用 `${ENV:AEGIS_BARK_URL}` 引用 |
| 高 | PyInstaller 配置附带整个私人 `workflows/` 目录 | 仅附带 `examples/workflows/` 和经过审阅的图片模板；私人图纸、数据库、队列均不参与打包 |
| 高 | 缺少 Git 忽略规则，工作目录混有环境、模型、旧 EXE、备份及个人设置 | 新增根目录白名单、源码导出白名单及凭据扫描；同时检查 Git 索引的文件名和暂存内容 |
| 中 | 源码写死用户目录、llama 安装位置、CUDA 版本及网页来源 | 使用当前用户目录、活动 Python 包、环境变量与可编辑配置；默认网页来源留空 |
| 中 | 旧打包辅助脚本会删除 spec 和批量清理目录 | 改为先审计、再调用受审阅 spec，不再执行这些清理 |
| 中 | 回归测试依赖私人图纸和机器用户名 | 使用脱敏的 `tests/fixtures/`，处理 Windows venv 启动器的 PID 测试差异 |

## 示例和文档

新增 5 个示例：文本显示、对象分支、数组反馈循环、Bark 通知、OK-WW 监控。前三个无需私人配置；后两个需要本地配置。OK-WW 示例默认保留终端，不执行休眠。

补齐依赖列表、安装与打包步骤、配置模板、示例说明、安全说明，以及 GitHub Actions 的隐私检查和 Windows Python 3.12 / 3.14 测试任务。AI 生成图纸提示词也改用凭据引用。

## 验证

- 原始基线 111 项测试通过；修改后共 125 项测试通过。
- 在独立源码目录及新建 Python 3.14.4 虚拟环境中，仅安装 `requirements.txt` 后运行完整测试通过；`pip check` 通过。未安装可选的 llama-cpp-python 或 DXCAM。
- 5 个示例均通过真实 Qt 加载，节点、配置与连线无丢失；前三个由真实引擎执行并验证最终结果。
- 发布文件通过常见 API / GitHub / AWS / JWT / Bearer 凭据、Bark 地址、私人目录、内网 URL 及本机已知敏感值检查；负向测试确认泄漏样本与旧暂存内容会被拦截。
- 在隔离的临时 Git 仓库中验证忽略规则及可提交文件范围。
- 初次源码审阅读取并执行 spec 配置阶段；随后为 v3.0.0 从隔离的公开源码快照构建 Windows x64 EXE，验证记录见下。
- 最终源码 ZIP 包含逐文件 SHA256 清单，解包后再次验证内容与测试。
- 首次发布后修复 Windows 子进程测试的清理竞态：等待探针进程退出后再读取结果并删除临时目录；连续 10 次实测通过。
- Qt 测试统一等待线程池并回收窗口和延迟删除对象，避免完整测试进程退出时的析构顺序异常。
- 源码发布至 [iLrs9935/AEGIS](https://github.com/iLrs9935/AEGIS)，远端文件的 Git blob 哈希已与本地提交逐项核对。云端隐私扫描、Windows Python 3.12 和 3.14 的 125 项测试已通过；最新提交状态见 [GitHub Actions](https://github.com/iLrs9935/AEGIS/actions)。

## 范围与限制

- 使用独立的公开源码目录初始化 Git 并推送；原始工作目录的私人资料、环境和旧构建未纳入提交。未审查作者其他仓库或过去是否曾有远端泄漏。
- 本机验证了 Python 3.14.4；Python 3.12 由 Windows 云端 CI 验证，未在本机另行安装。
- 本次没有发送真实 Bark 通知、启动游戏或 OK-WW、执行实际休眠；外部操作通过测试替身验证。
- 本地旧 EXE、备份、日志和通知队列可能仍含旧配置。它们保留在本地，不能直接作为此次 GitHub 附件上传。
- 静态扫描覆盖已知格式和本地已知值，并非对任意未知秘密的数学保证。新增附件和配置应继续经过检查。
- 按作者要求采用 MIT 许可证，保留作者版权与许可声明；作者署名使用 GitHub 账号 iLrs9935。

## 双语发布补充

- 软件新增即时中英文切换，新安装默认英文，支持 `--lang en` / `--lang zh`；切换保留图纸、配置、选中状态和撤销历史。
- 41 个内置节点的类型名称、分类、参数与选项具有英文显示；内部图纸标识保持兼容。用户填写的内容及部分后端诊断日志保留原文。
- 新增英文首页、中文说明和真实 Qt 主界面截图 `docs/screenshots/main-en.png`、`main-zh.png`，截图仅使用公开示例和隔离偏好，不含私人工作流列表或背景图。
- 维护状态为不定期维护 / occasional updates。
- 主页新增 SVG 封面、状态徽章、快速入口和双语外观画廊：五套皮肤、三种连线均使用真实 Qt 界面截图。自定义背景由作者生成，截图只显示公开示例；原始本地图片与个人偏好不纳入 Git。
- `scripts/capture_ui.py --gallery --background ...` 可在隔离偏好中重现主题、连线和双语界面预览，新增公开图片逐项加入发布白名单。

## Windows v3.0.0 免安装包验证

- 构建输入为 `3ab5fbe` 的 127 个公开文件；使用 Python 3.14.4、PyInstaller 6.20.0 和 Qt 6.11.2，EXE 文件版本为 3.0.0。
- 输出 Windows x64 免安装 ZIP、带逐文件清单的源码 ZIP，以及 `SHA256SUMS.txt`；包内附带依赖许可证、配置模板和五个公开示例。
- 本地构建先完成验证；正式附件由 GitHub Windows 构建机从同一源提交生成并上传。回下载后，对正式压缩包的 1,374 个文件逐项核对 SHA256，并用本机已知私人配置值检查全部解压内容。运行测试使用另行解压的副本，测试日志和偏好不会回到发布包。
- 在移除开发工具 PATH 的环境下，英语和中文主窗口均成功启动，Qt 模块从包内加载，ICU 从 Windows System32 加载，加载图纸未被修改。
- 使用打包后的 EXE 实际执行文本、对象分流和数组循环三个示例，输出符合预期，三个进程均正常退出，退出码为 0。
- 对应源码的云端隐私扫描与 Windows Python 3.12 / 3.14 测试通过。没有通过本次二进制测试发送真实 Bark 通知、启动游戏或 OK-WW、执行休眠。
- EXE 未签名；基础免安装版不包含可选 llama-cpp-python、模型、CUDA 库或 DXCAM。AEGIS 源码保持 MIT，第三方组件许可证随包保留。

## 2026-11-14 工程整改复核（本地未发布候选）

以上 v3.0.0 历史发布记录保留其原始验证范围，不能代替此次修改的测试。此次以本地现有源码 125 项通过为基线，新增 47 个测试方法；未推送代码或运行更新后的云端 CI。

本机 Windows 11 的 Python 3.12.8、3.13.12、3.14.4 分别执行同一套 172 项：发现 172、实际执行 172、通过 172、失败 0、错误 0、跳过 0、未执行 0。互斥分层：Unit 83、Integration 44、Security 43、Windows Runtime 2。Mock 辅助标签 132，真实 Qt 标签 46，明确原生 Windows API 探针 2，标签互相重叠，不可相加或相减当成总数。三个环境的 pip check 均通过。

逐测试 ID、子情景、环境与 Python 源码 SHA256 记录在 `release/remediation-tests-py312.json`、`remediation-tests-py313.json`、`remediation-tests-py314.json`，日志同目录。计数口径及命令见 [TESTING.md](docs/TESTING.md)。所有破坏性 HAL 在测试中使用替身；真实 Windows 探针仅验证临时子进程和 DLL 搜索路径，不代表实际键鼠、关进程、Bark、游戏或休眠成功。

执行边界现按 41 节点真实行为分类，高风险工作流每次需明确授权，直接调用引擎/Worker 同样检查，跳转图纸重新审查。--safe-power 改为工作流只读能力策略，不宣称为系统沙箱。旧点击 JSON 提示迁移为指定坐标，缺坐标不会隐式原地连点。19 个工作流 JSON 兼容性检查均通过，原文件未改写。

新本地构建输出位于 `release/remediation-20261114/`，不会覆盖历史 v3.0.0。实际 EXE 场景使用独立 `release/remediation-packaged.json`（三项文本/数据执行及一项拒绝未经授权系统节点），双语启动证据使用 `release/remediation-startup-en.json` / `remediation-startup-zh.json`。只有对应报告实际存在且通过，才可记录为已验证；构建成功和源码测试通过都不能代替这些结果。上述自动化验证未执行真实 Bark、OK-WW/游戏、键鼠输入或系统休眠；这四类实际操作现已由用户确认人工实测通过，见下方人工验证补记。可选模型尚无实际验证记录。

修改文件、根因、并发语义、迁移、测试及已知限制见 [ENGINEERING_REMEDIATION.md](docs/ENGINEERING_REMEDIATION.md)。发布 CI 新增同源三版本测试门禁、双语启动和 EXE 执行情景门禁；本次仅本地验证，不声称更新后的 GitHub Actions 已运行。

### 本地 EXE 实际验证结果（2026-11-14）

- `release/remediation-packaged.json` 已生成：4/4 场景通过，真实运行新打包 EXE；文本、对象分流、数组反馈输出正确，未经授权系统节点被拒绝。没有执行实际电源操作。
- `release/remediation-startup-en.json`、`remediation-startup-zh.json` 已生成：2/2 双语原生窗口启动通过，包内 Qt 与 Windows System32 ICU 正确，加载的工作流哈希未变化。
- EXE SHA256：`8b955419ddb235b77ce249d52d6e9cff7ea4183fb378d99ba3f241d0bccc79cf`。
- 免安装 ZIP SHA256：`c2110b2cb3cd706d2d2854fa6f94d57828ad01d032d5beb427c1e44c7fecaac7`；1,423 个载荷文件逐项清单校验通过（加清单自身共 1,424 文件），全部 Python 源码哈希与三个环境的测试证据一致。
- 最终审计文档在上述验证后补记；免安装包保留构建时的文档快照。补记后的完整源码另导出 `release/AEGIS-engineering-remediation-source.zip`，Python 代码与候选 EXE 构建输入完全一致。

### 用户人工实测补记（确认于 2026-11-14）

用户确认：真实键鼠操作、Bark 通知、OK-WW/游戏实际运行、系统实际休眠，均已人工实测通过。记录方式为“用户人工实测通过”，详细范围及来源见 [MANUAL_VALIDATION.md](docs/MANUAL_VALIDATION.md)。具体实测日期与所测版本/二进制哈希未单独提供，不将其绑定到某个 EXE。

这是四类人工验证覆盖，不新增自动化测试数，不改写已有 Mock/Windows/EXE 原始报告，也不扩大此前历史版本的验证结论。当前公开文档补充 [LLM Workflow 快速入门](docs/LLM_WORKFLOW_QUICKSTART.md)，包含数据传递、分支、循环、安全约束和完整 JSON 示例。文档更新后的源码归档为 `release/AEGIS-engineering-remediation-source-r2.zip`；Python 代码与已验证版本一致，已有 EXE 和源码快照保留。

## v3.0.1 发布复核（2026-11-14）

本节对应此次 v3.0.1；上面的 172 项及未发布候选记录保留其历史范围。新增两项双语 LLM 图纸示例的结构/真实 Qt 加载与无副作用执行检查，以及一项 3.0.1 中英文窗口标题切换检查，当前共 175 个测试方法。

本地 Windows Python 3.12.8、3.13.12、3.14.4 分别实际运行 175/175，通过 175，失败 0、错误 0、跳过 0。互斥分层为 Unit 83、Integration 47、Security 43、Windows Runtime 2；重叠标签为 Mock 辅助 133、真实 Qt 49、明确原生 Windows API 探针 2。三个环境不累加为不同用例，原始报告保存在本地 `release/v301-tests-py312.json`、`v301-tests-py313.json`、`v301-tests-py314.json`。

README 中英版本、下载地址、窗口标题、PyInstaller 文件版本、默认构建版本和发布工作流输入统一为 3.0.1。LLM 快速构筑提供[中文](docs/LLM_WORKFLOW_QUICKSTART.md)和[English](docs/LLM_WORKFLOW_QUICKSTART.en.md)两份等价指南，内部节点类型、配置键、枚举和端口仍使用兼容中文标识。人工实测与详细实验/工程记录正文保留中文，外文 README 提供入口。

用户人工确认通过的键鼠、Bark、OK-WW/游戏与休眠仍按[人工记录](docs/MANUAL_VALIDATION.md)单独统计，不据此补造版本哈希或自动化通过记录。新发布附件从指定 Git 源提交构建；必须通过云端三版本源码检查、双语实际 EXE 启动和四个实际 EXE 场景，再将草稿发布。云端运行结果以本次 GitHub Actions 和发布页附带的结果为准，不能用此前 v3.0.0 云端结果替代。

v3.0.1 包含全部工程整改：运行实例上下文与信号隔离、复合更新、点击明确模式与旧 JSON 迁移、集中执行授权、只读安全模式及分层测试/发布门禁。旧工作流需要检查点击迁移提示；--safe-power 现在拒绝高风险工作流能力，不再仅拦截电源 HAL。它不是操作系统沙箱。
