# AEGIS — Visual Automation Workflows

English | [简体中文](README.zh-CN.md)

AEGIS is a Windows desktop workflow editor for connecting computer vision, mouse and keyboard actions, text, logic, persistent memory, notifications, local AI, and system operations on a node canvas.

**Maintenance: occasional updates. There is no fixed maintenance or release schedule.**

## English interface

![AEGIS English main interface](docs/screenshots/main-en.png)

## 中文主界面 / Chinese interface

![AEGIS Chinese main interface](docs/screenshots/main-zh.png)

## Features

- Zoomable canvas with selection, copy and paste, undo and redo, and reusable logic groups.
- Standard cards or compact icons, with curved, orthogonal, or circuit-style connections.
- A configuration inspector that appears when a node is selected.
- One `value` per edge: booleans, numbers, strings, objects, arrays, or null.
- Strict input contracts and explicit routing rules; invalid input stops the workflow.
- JSON workflows that can be inspected, saved, reused, and generated with AI assistance.
- English and Simplified Chinese interface controls, node menus, configuration labels, choices, and port labels.
- Optional local model inference, browser scraping, and reliable Bark notifications with a local outbox.

## Install and launch

Requires **Windows** and **Python 3.12–3.14**. The source repository excludes private workflows, local settings, databases, Python environments, model weights, and native DLL bundles.

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py --lang en
```

New installations start in English. Use the **EN / 中文** menu at the top right to switch immediately; the application remembers the selection. You can also use `--lang zh` or set `AEGIS_LANGUAGE` to `en` or `zh`.

Switching languages preserves the graph, selection, settings, and undo history. Workflow type names, configuration keys, and port identifiers retain their compatible serialized format. User-authored text and paths stay as entered; diagnostic messages from individual backends may retain their original language.

Open a public example:

```powershell
python main.py --lang en --file examples/workflows/01_hello_text.json
```

Add `--autorun` to execute after loading. On startup, missing examples are copied into the local `workflows/` list; existing files are preserved.

## Example workflows

| Example | Purpose | Configuration |
| --- | --- | --- |
| [Text and wait](examples/workflows/01_hello_text.json) | Enter text, wait briefly, and display it | None |
| [Value routing](examples/workflows/02_value_router.json) | Route an object by its `found` field and merge branches | None |
| [Array loop](examples/workflows/03_array_loop.json) | Iterate over three items using a feedback connection | None |
| [Bark notification](examples/workflows/04_bark_notification.json) | Send a completion notification, with a durable outbox | Requires `AEGIS_BARK_URL`; sends a real notification |
| [OK-WW supervision](examples/workflows/05_okww_supervision.json) | Check ownership, monitor logs, retry, and clean up a task session | Requires `AEGIS_OKWW_EXE` and installation-specific paths; keeps the terminal open by default |

The first three examples only process text and data. The OK-WW example can launch applications and terminate processes owned by its task session; inspect its configuration before using it.

## Private configuration

```powershell
Copy-Item config.local.example.json config.local.json
```

Edit `config.local.json` locally to provide actual values. Alternatively, supply process environment variables with the same names. Environment variables take precedence.

In a node's `config`, use a reference such as `${ENV:AEGIS_BARK_URL}`. AEGIS resolves it just before execution and preserves the reference when saving the graph. A missing explicit reference fails the node. A blank Bark URL uses `AEGIS_BARK_URL` automatically; if neither is set, notification delivery is skipped.

Keep device URLs, API keys, and other credentials out of public examples. `config.local.json`, local workflows, logs, databases, backgrounds, and notification queues are ignored by Git. AEGIS does not automatically load `.env` files.

For optional local AI inference, install a suitable `llama-cpp-python` build and select a local GGUF model. Native library discovery uses the active Python package or application bundle. `AEGIS_LLAMA_LIB` can override the library directory; CUDA discovery respects `CUDA_PATH` or `CUDA_HOME`. DXCAM is an optional capture backend.

## Using the canvas

1. Right-click empty canvas space to add a node.
2. Connect an output port to the next node's `IN` port.
3. Select a node to edit its parameters and input/output contracts.
4. Hover over a node to inspect port descriptions.
5. Press **F5** to run and **Shift+F5** to stop.

| Shortcut | Action |
| --- | --- |
| Ctrl+S | Save workflow |
| Ctrl+Z | Undo |
| Ctrl+Y / Ctrl+Shift+Z | Redo |
| Ctrl+C / Ctrl+V | Copy / paste selected nodes and groups |
| Delete / Backspace | Delete selection |
| Ctrl+G | Create a locked group from selected nodes |
| Ctrl+B | Toggle the workflow sidebar |
| F5 / Shift+F5 | Run / stop |

Text fields keep their normal editing shortcuts. Double-click a node to switch between icon and standard-card views.

## Workflow format

A workflow contains `meta`, `nodes`, `groups`, and `edges`. Each edge carries one value plus its source node and output port. Receiver contracts accept `any`, `boolean`, `number`, `string`, `object`, `array`, or `null`.

Node execution status is separate from business data: an image search returning `found: false` is a valid result; a capture backend exception is a failure. Use a Value router for branches.

Inspect the included examples for complete JSON documents. The detailed [Chinese workflow-generation prompt](AI_WORKFLOW_PROMPT.md) lists canonical node identifiers and schemas. These identifiers remain the same in the English interface.

## Tests and source publishing

```powershell
python -m unittest discover -s tests -v
python scripts/check_release.py
python scripts/export_github.py --output release/AEGIS-github-source.zip
```

The export script audits an explicit allowlist, excludes local private data, and adds a per-file SHA256 manifest. The audit also checks the Git index for private files and stale staged credentials. Do not upload an archive of the entire working directory or reuse old binaries and backups as release attachments.

GitHub Actions runs the source audit and Windows tests on Python 3.12 and 3.14. The Windows-specific application features do not run on Linux or macOS.

## Build an executable

```powershell
python -m pip install -r requirements-build.txt
python pyinstaller.py
```

The build uses the reviewed spec and only includes public workflows and approved image templates. Optional native inference DLLs require `AEGIS_BUNDLE_LLAMA=1` and locally supplied dependencies under `dlls/`.

AEGIS performs real keyboard, mouse, process, and power actions. Inspect unfamiliar workflows before running them. `--safe-power` intercepts hibernation and terminal exit; other actions still execute.

## Maintenance and license

Maintenance is **occasional / 不定期维护**. Issues and pull requests are welcome; response times and future releases are not guaranteed.

Copyright © 2026 [iLrs9935](https://github.com/iLrs9935). Licensed under the [MIT License](LICENSE). Preserve the copyright and license notice when distributing copies or derivatives.

See [security and private configuration notes](SECURITY.md) and the [release review](RELEASE_REVIEW.md) for the publication boundaries.
