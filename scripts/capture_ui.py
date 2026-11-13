"""Capture real bilingual UI, theme and connection previews with isolated preferences."""

import argparse
import gc
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import QCoreApplication, QEvent, QPointF, QRectF, Qt
from PyQt6.QtGui import QFont, QFontDatabase, QPixmap
from PyQt6.QtWidgets import QApplication
from core.event_bus import bus
from ui import theme
from ui.graph_items import NodeItem
from ui.graph_view import AEGISScene
from ui.i18n import set_language
from ui.main_window import MainWindow


def capture(output: Path, gallery=False, background=None, background_opacity=0.58):
    root = Path(__file__).resolve().parents[1]
    app = QApplication.instance() or QApplication([])
    fonts = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts"
    for name in ("segoeui.ttf", "seguisym.ttf", "seguiemj.ttf", "msyh.ttc", "arial.ttf", "consola.ttf"):
        path = fonts / name
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont("Segoe UI", 10))
    image = QPixmap(str(background)) if background else None
    if image is not None and image.isNull():
        raise ValueError("Could not load the supplied background image")
    variants = [("main", "Command Terminal", "curve", False, False)]
    if gallery:
        if image is not None:
            variants.append(("theme-custom-background", "Command Terminal", "curve", True, False))
        variants.extend([
            ("theme-night-city", "夜之城", "curve", False, False),
            ("theme-classic", "AEGIS Classic", "curve", False, False),
            ("theme-pop-art", "波普撞色", "curve", False, False),
            ("theme-abyssal", "Abyssal", "curve", False, False),
            *[(f"connections-{style}", "Command Terminal", style, False, True)
              for style in ("curve", "orthogonal", "circuit")],
        ])
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        preferences = Path(directory)
        with patch.object(theme, "CONFIG_FILE", str(preferences / "settings.json")), patch.object(
            AEGISScene, "_get_config_path", return_value=str(preferences / "background.json")
        ):
            for locale in ("en", "zh"):
                for slug, preset, edge_style, custom, canvas_only in variants:
                    set_language(locale)
                    window = MainWindow()
                    try:
                        window.workflow_dir = str(root / "examples" / "workflows")
                        window.refresh_workflow_list()
                        window.resize(1600, 960)
                        assert window.load_graph_from_json(str(root / "examples/workflows/02_value_router.json"))
                        window.console.clear()
                        window.on_theme_changed(preset)
                        window.on_edge_style_changed(edge_style)
                        if custom:
                            window.scene.bg_pixmap = image
                            window.scene.bg_image_path = str(background)
                            window.scene.bg_opacity = background_opacity
                        source = next(item for item in window.scene.items() if isinstance(item, NodeItem) and item.id == "source")
                        source.setSelected(True)
                        window.show()
                        for _ in range(3):
                            app.processEvents()
                        window.main_h_splitter.setSizes([225, 1015, 360])
                        window.right_v_splitter.setSizes([710, 180])
                        window.view.fitInView(QRectF(-65, -200, 1150, 500), Qt.AspectRatioMode.KeepAspectRatio)
                        if custom:
                            window.view.centerOn(QPointF(510, -110))
                        app.processEvents()
                        destination = output / f"{slug}-{locale}.png"
                        if canvas_only:
                            bounds = window.scene.itemsBoundingRect().adjusted(-35, -35, 35, 35)
                            region = window.view.mapFromScene(bounds).boundingRect()
                            region = region.intersected(window.view.viewport().rect())
                            screenshot = window.view.viewport().grab(region)
                        else:
                            screenshot = window.grab()
                        if not screenshot.save(str(destination)):
                            raise RuntimeError("Screenshot could not be saved")
                        print(destination, flush=True)
                    finally:
                        window.close()
                        bus.node_status_changed.disconnect(window.engine._on_node_status_changed)
                        bus.log_emitted.disconnect(window.append_log)
                        bus.dag_completed.disconnect(window._on_dag_completed)
                        bus.blueprint_jump_requested.disconnect(window.handle_blueprint_jump)
                        window.deleteLater()
                        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                        app.processEvents()
                        gc.collect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/screenshots"))
    parser.add_argument("--gallery", action="store_true", help="Include built-in themes and all connection styles")
    parser.add_argument("--background", type=Path, help="Optional local image for the custom-background preview")
    parser.add_argument("--background-opacity", type=float, default=0.58)
    args = parser.parse_args()
    if not 0 < args.background_opacity <= 1:
        parser.error("--background-opacity must be greater than 0 and at most 1")
    capture(args.output.resolve(), args.gallery, args.background, args.background_opacity)
