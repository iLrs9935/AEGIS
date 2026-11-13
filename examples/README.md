# 示例工作流

源码启动后会将示例复制到本地 `workflows/` 列表，仅补齐缺失文件。也可以直接指定文件：

```powershell
python main.py --file examples/workflows/01_hello_text.json
```

加载后按 F5 执行，Shift+F5 停止。加 `--autorun` 可在加载后执行。

| 文件 | 演示内容 | 配置与实际操作 |
| --- | --- | --- |
| `01_hello_text.json` | 文本输入 → 等待 → 文本展示 | 无需配置，只更新画布文字和日志 |
| `02_value_router.json` | 输出对象 → 判断 `found` → 分支汇合 | 无需配置；将输出覆盖值的 `found` 改为 `false` 可查看另一分支 |
| `03_array_loop.json` | 数组输入 → 遍历 → 展示 → 反馈循环 | 无需配置；依次展示 alpha、beta、gamma 后结束 |
| `04_bark_notification.json` | 模拟完成状态 → 可靠 Bark 通知 | 需要 `AEGIS_BARK_URL`；会发送一条真实通知，失败后进入本地离线队列 |
| `05_okww_supervision.json` | OK-WW 预检、监控、重试及清理 | 需要 `AEGIS_OKWW_EXE`，按安装情况调整日志和脚本路径；会启动应用并可能关闭该次会话的进程，默认保留终端、不休眠 |

复制 `config.local.example.json` 为 `config.local.json` 后在本机填写实际值，或者使用环境变量。环境变量优先。图纸中用 `${ENV:变量名}` 引用；仅节点 `config` 支持该解析语法，运行时解析不会写回文件。未配置的显式引用会使该节点失败。

Bark 节点的地址留空时会自动读取 `AEGIS_BARK_URL`，两者均为空则跳过通知。公开示例和测试不包含设备密钥。请勿将真实地址写回示例文件；自己的图纸保存在被忽略的 `workflows/` 下。

`tests/fixtures/` 内的完整兑换码、SDKDNS 和每日任务图纸是脱敏回归样本。它们使用测试地址和虚构路径，供测试校验，不适合直接作为无人值守任务运行。
