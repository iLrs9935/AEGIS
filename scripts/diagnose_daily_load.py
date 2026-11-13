"""Read-only UI graph audit. Never starts the engine or node functions."""
import json
import os
import sys
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt6.QtWidgets import QApplication
from ui.main_window import MainWindow
from ui.graph_items import NodeItem

app = QApplication([])
path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding='utf-8'))
window = MainWindow()
assert window.load_graph_from_json(str(path))
items = {n.id: n for n in window.scene.items() if isinstance(n, NodeItem)}
edges = [(o.parentItem().id, o.name, i.parentItem().id, i.name)
         for i, o, _ in window.scene.connections]
print('JSON nodes/edges:', len(data['nodes']), len(data['edges']))
print('UI nodes/edges:', len(items), len(edges))
for n in data['nodes']:
    actual = items[n['id']].get_config()
    for key, value in n.get('config', {}).items():
        if actual.get(key) != value:
            print('CONFIG CHANGED:', n['id'], n['type'], key)
            if n['type'] in ('系统休眠', 'OK-WW监控初始化', '启动程序'):
                print('  ', repr(value), '=>', repr(actual.get(key)))
for e in data['edges']:
    if not any(s == e['src_id'] and p == e['src_port'] and t == e['tgt_id']
               for s, p, t, _ in edges):
        print('DROPPED EDGE:', e)
        print('source ports:', [p.name for p in items[e['src_id']].out_ports])
window.engine.load_from_ui({i: {'name': n.node_type, 'config': n.get_config()}
                           for i, n in items.items()}, edges)
print('ROOTS:', [(i, items[i].name) for i in items if not any(
    not d.get('is_feedback') for _, _, d in window.engine.graph.in_edges(i, data=True))])
print('FEEDBACK:', [(s, d['src_port'], t) for s, t, d in window.engine.graph.edges(data=True)
                    if d.get('is_feedback')])
window.close()
