"""Persist routing evidence before an abrupt process exit; never log configs."""
import ast
import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PyQt6.QtCore import Qt
from core.event_bus import bus


def redact(text):
    return re.sub(r'https?://[^\s<>\"\x27]+', '[URL已隐藏]', str(text))


class RunLog:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / 'aegis-run.log'
        self.logger = logging.Logger('aegis-run', logging.INFO)
        self.handler = RotatingFileHandler(self.path, maxBytes=4_000_000, backupCount=5, encoding='utf-8')
        self.handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
        self.logger.addHandler(self.handler)
        bus.log_emitted.connect(self.on_log, Qt.ConnectionType.DirectConnection)
        bus.node_status_changed.connect(self.on_node, Qt.ConnectionType.DirectConnection)

    def on_log(self, level, module, message):
        self.logger.info('[%s] [%s] %s', level, module, redact(message))

    def on_node(self, node_id, status, result):
        if status == 'Idle':
            return
        port = ''
        if status == 'Success':
            try:
                value = ast.literal_eval(result)
                port = value.get('active_ports', value.get('active_port', 'OUT'))
            except (ValueError, SyntaxError, AttributeError):
                port = 'unparsed'
        self.logger.info('[Node] %s %s port=%s', node_id, status, redact(port))

    def close(self):
        bus.log_emitted.disconnect(self.on_log)
        bus.node_status_changed.disconnect(self.on_node)
        self.handler.close()
