# AEGIS v3.0.0 — Windows x64 portable edition

## English

1. Extract the complete ZIP into a writable folder.
2. Run **AEGIS Command Terminal.exe**. Keep the executable and `_internal` together.
3. Choose **EN / 中文** at the top right to switch the interface language.
4. Open one of the five included workflows. The first three examples only process text and data.

Python is included. This package does not require a separate Python installation.

For Bark or other private values, copy `config.local.example.json` to `config.local.json` beside the executable and fill it in locally, or set the corresponding environment variables. Personal configuration and private workflows are not supplied.

The portable edition includes the standard workflow editor, vision/keyboard/mouse features and OK-WW nodes. Optional llama-cpp-python, GGUF models, CUDA libraries and DXCAM are not bundled. Use a source build with the required optional dependencies for those backends. OK-WW itself is a separate application.

The Windows executable is not code-signed. AEGIS source uses the MIT license; bundled dependencies retain their own licenses, including GPL-licensed PyQt6. Read `THIRD_PARTY_NOTICES.txt` and `THIRD_PARTY_LICENSES` for the component notices and source-distribution links.

Project, source and issues: https://github.com/iLrs9935/AEGIS

## 中文

1. 将整个 ZIP 解压到可写目录。
2. 运行 **AEGIS Command Terminal.exe**，让 EXE 和 `_internal` 保持在同一目录。
3. 用右上角 **EN / 中文** 切换界面语言。
4. 打开附带的五个示例工作流；前三个示例只处理文本和数据。

安装包已包含 Python 运行时，无需单独安装 Python。

Bark 等私人参数可通过 EXE 同目录的 `config.local.json` 或环境变量提供。可先复制 `config.local.example.json` 再填写；发布包不包含作者的私人配置和工作流。

免安装版包含标准工作流编辑器、视觉/键鼠功能与 OK-WW 节点，不附带可选的 llama-cpp-python、GGUF 模型、CUDA 库或 DXCAM。需要这些后端时，请安装相应可选依赖并从源码构建。OK-WW 本体需要单独安装。

Windows EXE 未做代码签名。AEGIS 源码采用 MIT，附带依赖各自保留原许可证，包括采用 GPL 的 PyQt6；依赖声明、许可证和源码分发链接见 `THIRD_PARTY_NOTICES.txt` 与 `THIRD_PARTY_LICENSES`。

项目、源码与问题反馈：https://github.com/iLrs9935/AEGIS
