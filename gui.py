# gui.py

import sys
from PyQt5.QtWidgets import (
    QMainWindow, QApplication, QWidget, QPushButton,
    QGraphicsScene, QGraphicsView, QLabel, QVBoxLayout,
    QHBoxLayout, QTableWidget, QTableWidgetItem, QComboBox,
    QPlainTextEdit, QDockWidget, QFormLayout
)
from PyQt5.QtCore import Qt, QTimer, QPointF
from PyQt5.QtGui import QBrush, QPen, QColor, QPainter
from engine import SimulationEngine
from packets import Packet
from node import Node

class TopologyView(QGraphicsView):
    """
    A subclass of QGraphicsView that overrides mousePressEvent
    so that clicking on a node circle selects it and notifies the
    main window to show node details.
    """
    def __init__(self, scene, parent_window):
        super().__init__(scene)
        self.parent_window = parent_window
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setRenderHint(QPainter.Antialiasing)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            scene_pos = self.mapToScene(event.pos())
            items = self.scene().items(QPointF(scene_pos.x(), scene_pos.y()))
            for item in items:
                node_id = item.data(0)
                if node_id is not None:
                    self.parent_window.show_node_details(node_id)
                    break
        super().mousePressEvent(event)

    def wheelEvent(self, event):
        angle = event.angleDelta().y()
        factor = 1.2 if angle > 0 else 1 / 1.2
        self.scale(factor, factor)

class GraphNodeItem:
    def __init__(self, node_id, x, y, radius=5, is_sink=False, is_mobile=False):
        self.node_id = node_id
        self.x = x
        self.y = y
        self.radius = radius
        self.is_sink = is_sink
        self.is_mobile = is_mobile
        self.item = None  # QGraphicsEllipseItem

class MainWindow(QMainWindow):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.setWindowTitle("RouMBLE BLE Mesh Simulator (2 Sinks + 3 Phones)")
        self.resize(1200, 800)

        central = QWidget()
        self.setCentralWidget(central)
        h_layout = QHBoxLayout(central)

        # --- Topology (Graphics) ---
        self.scene = QGraphicsScene(0, 0, self.engine.width, self.engine.height)
        self.view = TopologyView(self.scene, self)
        h_layout.addWidget(self.view, 3)

        self.graph_nodes = {}

        # --- Right Panel (controls & info) ---
        right_panel = QWidget()
        r_layout = QVBoxLayout(right_panel)
        h_layout.addWidget(right_panel, 1)

        # Start / Pause / Step
        btn_layout = QHBoxLayout()
        self.btn_start = QPushButton("Start")
        self.btn_pause = QPushButton("Pause")
        self.btn_step = QPushButton("Step")
        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_pause)
        btn_layout.addWidget(self.btn_step)
        r_layout.addLayout(btn_layout)
        self.btn_start.clicked.connect(self.on_start)
        self.btn_pause.clicked.connect(self.on_pause)
        self.btn_step.clicked.connect(self.on_step)

        # Metric Dashboard
        self.lbl_pdr = QLabel("PDR:   0.00%")
        self.lbl_latency = QLabel("Avg Latency:   0.00s")
        self.lbl_hops = QLabel("Avg Hops:   0.00")
        self.lbl_overhead = QLabel("Overhead:   0.00")
        self.lbl_routing_updates = QLabel("Routing Updates:   0")
        r_layout.addWidget(self.lbl_pdr)
        r_layout.addWidget(self.lbl_latency)
        r_layout.addWidget(self.lbl_hops)
        r_layout.addWidget(self.lbl_overhead)
        r_layout.addWidget(self.lbl_routing_updates)

        # External Packet Injection Form
        inject_group = QWidget()
        inj_layout = QFormLayout(inject_group)
        self.cmb_src = QComboBox()
        self.cmb_src.addItem("ExternalDevice")
        for node in self.engine.nodes:
            self.cmb_src.addItem(f"Node{node.id}")
        self.cmb_dst = QComboBox()
        self.cmb_dst.addItem("Broadcast")
        for node in self.engine.nodes:
            if node.is_sink:
                self.cmb_dst.addItem(f"Sink{node.id}")
        self.cmb_type = QComboBox()
        self.cmb_type.addItems(["RMS", "SMS"])
        self.btn_send = QPushButton("Send Packet")
        inj_layout.addRow("Source:", self.cmb_src)
        inj_layout.addRow("Destination:", self.cmb_dst)
        inj_layout.addRow("Type:", self.cmb_type)
        inj_layout.addRow(self.btn_send)
        self.btn_send.clicked.connect(self.on_send_packet)
        r_layout.addWidget(QLabel("External Packet Injection"))
        r_layout.addWidget(inject_group)

        # Selected Node Label
        self.selected_label = QLabel("Selected Node: None")
        r_layout.addWidget(self.selected_label)

        # Node Detail Table
        r_layout.addWidget(QLabel("Node Details"))
        self.node_table = QTableWidget(0, 3)
        self.node_table.setHorizontalHeaderLabels(["Neighbors", "Routing Table", "Energy"])
        r_layout.addWidget(self.node_table)

        r_layout.addStretch()

        # --- Log Panel (Dockable) ---
        self.log_dock = QDockWidget("Event Log", self)
        self.log_widget = QPlainTextEdit()
        self.log_widget.setReadOnly(True)
        self.log_dock.setWidget(self.log_widget)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.log_dock)

        # --- QTimer to advance sim & update UI ---
        self.timer = QTimer()
        self.timer.setInterval(100)  # 100 ms → 0.1s sim time
        self.timer.timeout.connect(self.on_timeout)
        self.sim_running = False

        self.draw_network()

    def draw_network(self):
        self.scene.clear()
        self.graph_nodes.clear()

        # Draw links
        pen_link = QPen(Qt.gray)
        drawn = set()
        for node in self.engine.nodes:
            for nbr in node.neighbors:
                pair = tuple(sorted((node.id, nbr.id)))
                if pair in drawn:
                    continue
                drawn.add(pair)
                x1, y1 = node.x, node.y
                x2, y2 = nbr.x, nbr.y
                self.scene.addLine(x1, y1, x2, y2, pen_link)

        # Draw nodes
        for node in self.engine.nodes:
            x, y = node.x, node.y
            r = 6
            if node.is_sink:
                color = QColor('red')
            elif node.is_mobile:
                color = QColor('green')
            else:
                color = QColor('blue')
            brush = QBrush(color)
            pen = QPen(Qt.black)
            ellipse = self.scene.addEllipse(x - r, y - r, 2*r, 2*r, pen, brush)
            ellipse.setData(0, node.id)
            ellipse.setFlag(ellipse.ItemIsSelectable, True)
            gni = GraphNodeItem(node_id=node.id,
                                x=x, y=y,
                                radius=r,
                                is_sink=node.is_sink,
                                is_mobile=node.is_mobile)
            gni.item = ellipse
            self.graph_nodes[node.id] = gni

    def on_timeout(self):
        self.engine.step(0.1)
        self.draw_network()

        # Update metrics
        metrics = self.engine.logger.get_metrics()
        pdr = metrics['pdr'] * 100.0
        self.lbl_pdr.setText(f"PDR:   {pdr:.1f}%")
        self.lbl_latency.setText(f"Avg Latency:   {metrics['avg_latency']:.2f}s")
        self.lbl_hops.setText(f"Avg Hops:   {metrics['avg_hops']:.2f}")
        self.lbl_overhead.setText(f"Overhead:   {metrics['overhead']:.2f}")
        self.lbl_routing_updates.setText(f"Routing Updates:   {metrics['routing_updates']}")

        while self.engine.logger.entries:
            entry = self.engine.logger.entries.pop(0)
            self.log_widget.appendPlainText(entry)

    def on_start(self):
        if not self.sim_running:
            self.sim_running = True
            self.timer.start()

    def on_pause(self):
        if self.sim_running:
            self.timer.stop()
            self.sim_running = False

    def on_step(self):
        if self.sim_running:
            self.on_pause()
        self.engine.step(0.1)
        self.draw_network()
        metrics = self.engine.logger.get_metrics()
        pdr = metrics['pdr'] * 100.0
        self.lbl_pdr.setText(f"PDR:   {pdr:.1f}%")
        self.lbl_latency.setText(f"Avg Latency:   {metrics['avg_latency']:.2f}s")
        self.lbl_hops.setText(f"Avg Hops:   {metrics['avg_hops']:.2f}")
        self.lbl_overhead.setText(f"Overhead:   {metrics['overhead']:.2f}")
        self.lbl_routing_updates.setText(f"Routing Updates:   {metrics['routing_updates']}")
        while self.engine.logger.entries:
            entry = self.engine.logger.entries.pop(0)
            self.log_widget.appendPlainText(entry)

    def on_send_packet(self):
        src_text = self.cmb_src.currentText()
        dst_text = self.cmb_dst.currentText()
        pkt_type = self.cmb_type.currentText()

        if src_text == "ExternalDevice":
            if pkt_type == "SMS":
                src_id = 0
            else:
                src_id = len(self.engine.sink_positions) + self.engine.mesh_count
        else:
            src_id = int(src_text.replace("Node", ""))

        if dst_text == "Broadcast":
            dst_id = None
        else:
            dst_id = int(dst_text.replace("Sink", ""))

        node_src = self.engine.node_map[src_id]
        node_src.seq_num += 1
        seq = node_src.seq_num
        ts = self.engine.env.now

        if pkt_type == "SMS":
            sink_id = dst_id if dst_id is not None else 0
            packet = Packet(
                pkt_type='RMS',
                src=src_id,
                sink_id=sink_id,
                seq=seq,
                hop_count=Node.MAX_HOPS,
                origin=src_id,
                timestamp=ts
            )
            self.engine.logger.record_data_sent()
            self.engine.logger.log_event(ts, 'SMS→RMS', src_id, sink_id)
            self.engine.node_map[src_id].env.process(
                self.engine.node_map[src_id].receive(packet)
            )
        else:
            rms = Packet(
                pkt_type='RMS',
                src=src_id,
                sink_id=dst_id,
                seq=seq,
                hop_count=Node.MAX_HOPS,
                origin=src_id,
                timestamp=ts
            )
            self.engine.logger.record_data_sent()
            self.engine.logger.log_event(ts, 'RMS_INJ', src_id, dst_id if dst_id is not None else -1)
            self.engine.node_map[src_id].env.process(
                self.engine.node_map[src_id]._broadcast(rms)
            )

    def show_node_details(self, node_id):
        # Update "Selected Node" label
        self.selected_label.setText(f"Selected Node: {node_id}")

        node = self.engine.node_map[node_id]
        neighbors = [str(n.id) for n in node.neighbors]

        # Format routing entries as "D:<dest>  NH:<next hop>"
        routing_entries = []
        for sink, info in node.routing_table.items():
            next_hop, hop_dist, _ = info
            routing_entries.append(f"D:{sink}   NH:{next_hop}")

        neighbors_str = "\n".join(neighbors) if neighbors else "(none)"
        routing_str = "\n".join(routing_entries) if routing_entries else "(none)"
        energy = f"{node.energy:.1f}"

        self.node_table.setRowCount(1)
        item_n = QTableWidgetItem(neighbors_str)
        item_n.setTextAlignment(Qt.AlignTop)
        self.node_table.setItem(0, 0, item_n)

        item_r = QTableWidgetItem(routing_str)
        item_r.setTextAlignment(Qt.AlignTop)
        self.node_table.setItem(0, 1, item_r)

        item_e = QTableWidgetItem(energy)
        item_e.setTextAlignment(Qt.AlignCenter)
        self.node_table.setItem(0, 2, item_e)
