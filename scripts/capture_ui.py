"""Render the real bilingual application using public examples and isolated preferences."""

import argparse
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication
from core.event_bus import bus
from ui import theme
from ui.graph_items import NodeItem
from ui.graph_view import AEGISScene
from ui.i18n import set_language
from ui.main_window import MainWindow


def capture(output: Path):
    root = Path(__file__).resolve().parents[1]
    app = QApplication.instance() or QApplication([])
    fonts = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts"
    for name in ("segoeui.ttf", "seguisym.ttf", "seguiemj.ttf", "msyh.ttc", "arial.ttf", "consola.ttf"):
        path = fonts / name
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont("Segoe UI", 10))
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        preferences = Path(directory)
        with patch.object(theme, "CONFIG_FILE", str(preferences / "settings.json")), patch.object(
            AEGISScene, "_get_config_path", return_value=str(preferences / "background.json")
        ):
            for locale in ("en", "zh"):
                set_language(locale)
                theme.Theme.switch_theme("Command Terminal")
                window = MainWindow()
                window.workflow_dir = str(root / "examples" / "workflows")
                window.refresh_workflow_list()
                window.resize(1600, 960)
                assert window.load_graph_from_json(str(root / "examples/workflows/02_value_router.json"))
                source = next(item for item in window.scene.items() if isinstance(item, NodeItem) and item.id == "source")
                source.setSelected(True)
                window.show()
                for _ in range(3):
                    app.processEvents()
                window.main_h_splitter.setSizes([225, 1015, 360])
                window.right_v_splitter.setSizes([710, 180])
                window.view.fitInView(QRectF(-65, -200, 1150, 500), Qt.AspectRatioMode.KeepAspectRatio)
                app.processEvents()
                destination = output / f"main-{locale}.png"
                if not window.grab().save(str(destination)):
                    raise RuntimeError("Screenshot could not be saved")
                print(destination)
                window.close()
                bus.node_status_changed.disconnect(window.engine._on_node_status_changed)
                bus.log_emitted.disconnect(window.append_log)
                bus.dag_completed.disconnect(window._on_dag_completed)
                bus.blueprint_jump_requested.disconnect(window.handle_blueprint_jump)
                window.deleteLater()
                app.processEvents()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/screenshots"))
    capture(parser.parse_args().output.resolve())
