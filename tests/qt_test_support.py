"""Keep Qt test objects within the lifetime of the shared QApplication."""
import gc
import unittest

from PyQt6.QtCore import QCoreApplication, QEvent, QThreadPool
from PyQt6.QtWidgets import QApplication


class QtTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        try:
            if not QThreadPool.globalInstance().waitForDone(3000):
                raise AssertionError("Qt test workers did not finish")
            for widget in cls.app.topLevelWidgets():
                widget.close()
                widget.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            cls.app.processEvents()
            gc.collect()
        finally:
            super().tearDownClass()
