# codee.py
# Simulazione BLE Mesh RouMBLE per showroom con due stanze (rettangolo inferiore e superiore)
# Aggiunta rettangolo centrale con sink e light all'interno
# 2 sink, 10 luci statiche lungo muri esterni, + central light
# 4 visitatori mobili sul perimetro esterno, margine esterno 2m, margine centrale 0.5m

import sys
import simpy
import random
import math
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QPushButton,
    QGraphicsScene, QGraphicsView, QVBoxLayout, QHBoxLayout,
    QPlainTextEdit, QDockWidget
)
from PyQt5.QtCore import Qt, QTimer, QPointF
from PyQt5.QtGui import QPen, QBrush, QColor, QPainter

# -----------------------
# Pacchetto RouMBLE
# -----------------------
class Packet:
    def __init__(self, pkt_type, src, sink_id, seq,
                 hop_count=0, origin=None, dest=None,
                 dtype=None, timestamp=0.0):
        self.pkt_type = pkt_type
        self.src = src
        self.sink_id = sink_id
        self.seq = seq
        self.hop_count = hop_count
        self.origin = origin if origin is not None else src
        self.dest = dest
        self.dtype = dtype
        self.timestamp = timestamp

# -----------------------
# Logger
# -----------------------
class Logger:
    def __init__(self):
        self.entries = []
    def log_event(self, time, evt, src, dst):
        dst_str = f"Node{dst}" if dst != -1 else "All"
        self.entries.append(f"[{time:.2f}] {evt} {src}->{dst_str}")

# -----------------------
# Nodo
# -----------------------
class Node:
    COMM_RANGE = 30.0
    PROX_RANGE = 2.0
    MARGIN_EXT = 2.0
    MARGIN_CENT = 0.5
    MOVE_INTERVAL = 0.05   # much smoother movement
    MOVE_DIST = 0.01       # much smaller steps
    BOM_INTERVAL = 20.0
    TX_DELAY = 0.01
    RX_DELAY = 0.005
    MAX_HOPS = 3
    OFF_DELAY = 1.75

    def __init__(self, env, id, is_sink, is_mobile, pos, engine):
        self.env = env
        self.id = id
        self.is_sink = is_sink
        self.is_mobile = is_mobile
        self.x, self.y = pos
        self.engine = engine
        self.neighbors = []
        self.seen = set()
        self.seq = 0
        self.light = False
        self.target = None
        if is_sink:
            env.process(self.bom_proc())
        if is_mobile:
            env.process(self.mobile_proc())

    def bom_proc(self):
        while True:
            yield self.env.timeout(Node.BOM_INTERVAL)
            self.seq += 1
            p = Packet('BOM', self.id, self.id, self.seq,
                       hop_count=0, timestamp=self.env.now)
            self.engine.logger.log_event(self.env.now, 'BOM', self.id, -1)
            yield from self.broadcast(p)

    def mobile_proc(self):
        while True:
            if self.target is None:
                self.target = self.pick_outer_perimeter()
            yield self.env.timeout(Node.MOVE_INTERVAL)
            dx, dy = self.target[0] - self.x, self.target[1] - self.y
            dist = math.hypot(dx, dy)
            if dist < 0.1:
                self.target = self.pick_outer_perimeter()
                continue
            step = min(Node.MOVE_DIST, dist)
            new_x = self.x + step * dx / dist
            new_y = self.y + step * dy / dist
            # Clamp outer margin
            new_x = min(max(new_x, Node.MARGIN_EXT), self.engine.width - Node.MARGIN_EXT)
            new_y = min(max(new_y, Node.MARGIN_EXT), self.engine.height - Node.MARGIN_EXT)
            # Avoid central rectangle margin
            cx1, cy1, cx2, cy2 = self.engine.central_rect
            if cx1 - Node.MARGIN_CENT < new_x < cx2 + Node.MARGIN_CENT and cy1 - Node.MARGIN_CENT < new_y < cy2 + Node.MARGIN_CENT:
                self.target = self.pick_outer_perimeter()
                continue
            self.x, self.y = new_x, new_y
            self.engine.update_neighbors()
            # Prossimità luci
            for n in self.engine.nodes:
                if not (n.is_sink or n.is_mobile):
                    d2 = math.hypot(self.x - n.x, self.y - n.y)
                    if d2 <= Node.PROX_RANGE and not n.light:
                        self.send_sms(n.id)
                    if n.light and d2 > Node.PROX_RANGE:
                        env = self.env
                        env.process(self.delayed_off(n))

    def pick_outer_perimeter(self):
        # Perimetro esterno con margine MARGIN_EXT
        w, h = self.engine.width, self.engine.height
        m = Node.MARGIN_EXT
        left, right, top, bottom = m, w - m, m, h - m
        max_attempts = 100
        for _ in range(max_attempts):
            side = random.choice(['top', 'bottom', 'left', 'right'])
            if side == 'top':
                pos = (random.uniform(left, right), top)
            elif side == 'bottom':
                pos = (random.uniform(left, right), bottom)
            elif side == 'left':
                pos = (left, random.uniform(top, bottom))
            else:
                pos = (right, random.uniform(top, bottom))
            # Ensure at least 1m from other mobile nodes
            too_close = False
            for n in self.engine.nodes:
                if n.is_mobile and n is not self:
                    if math.hypot(n.x - pos[0], n.y - pos[1]) < 1.0:
                        too_close = True
                        break
            if not too_close:
                return pos
        # Fallback: just return a valid position
        return (left, top)

    def send_sms(self, target):
        self.seq += 1
        p = Packet('RMS', self.id, None, self.seq,
                   hop_count=Node.MAX_HOPS,
                   origin=self.id, dest=target,
                   dtype='Light', timestamp=self.env.now)
        self.engine.logger.log_event(self.env.now, 'SMS', self.id, target)
        # Inoltra a sink interni
        self.env.process(self.engine.sink1.receive(p))
        self.env.process(self.engine.sink2.receive(p))

    def delayed_off(self, n):
        yield self.env.timeout(Node.OFF_DELAY)
        d = math.hypot(self.x - n.x, self.y - n.y)
        if d > Node.PROX_RANGE and n.light:
            n.light = False
            self.engine.logger.log_event(self.env.now, 'LIGHT_OFF', self.id, n.id)

    def receive(self, p):
        yield self.env.timeout(Node.RX_DELAY)
        if p.pkt_type == 'RMS':
            yield from self.handle_rms(p)

    def handle_rms(self, p):
        key = (p.origin, p.seq)
        if key in self.seen: return
        self.seen.add(key)
        if p.dest == self.id and not (self.is_mobile or self.is_sink):
            self.light = True
            self.engine.logger.log_event(self.env.now, 'LIGHT_ON', p.origin, self.id)
        if p.hop_count > 1:
            p.hop_count -= 1
            self.engine.logger.log_event(self.env.now, 'RMS_FWD', self.id, -1)
            yield from self.broadcast(p)

    def broadcast(self, p):
        yield self.env.timeout(Node.TX_DELAY)
        for nb in self.neighbors:
            cp = Packet(p.pkt_type, p.src, p.sink_id,
                        p.seq, p.hop_count, p.origin,
                        p.dest, p.dtype, p.timestamp)
            self.env.process(nb.receive(cp))

    @staticmethod
    def pick_outer_start(engine):
        """
        Returns a random (x, y) position on the outer perimeter of the area.
        Adjust logic as needed for your simulation.
        """
        import random
        w, h = engine.width, engine.height
        # Pick a random side: 0=top, 1=bottom, 2=left, 3=right
        side = random.choice([0, 1, 2, 3])
        if side == 0:  # top
            x = random.uniform(0, w)
            y = 0
        elif side == 1:  # bottom
            x = random.uniform(0, w)
            y = h
        elif side == 2:  # left
            x = 0
            y = random.uniform(0, h)
        else:  # right
            x = w
            y = random.uniform(0, h)
        return x, y

# -----------------------
# Simulation Engine
# -----------------------
class SimulationEngine:
    def __init__(self, width=16, height=10,  # <-- larger area
                 num_luci=12, num_mobile=4):  # <-- increased num_luci from 10 to 12
        self.env = simpy.Environment()
        self.logger = Logger()
        self.width = width
        self.height = height
        # central rectangle coordinates (smaller)
        w, h = width, height
        self.central_rect = (w*0.4, h*0.4, w*0.6, h*0.6)
        self.nodes = []
        self.setup_nodes(num_luci, num_mobile)
        self.update_neighbors()

    def setup_nodes(self, m, n):
        # 2 sink centrati nella central rectangle
        x1 = (self.central_rect[0] + self.central_rect[2]) / 2 - 1
        x2 = (self.central_rect[0] + self.central_rect[2]) / 2 + 1
        y = (self.central_rect[1] + self.central_rect[3]) / 2
        self.sink1 = Node(self.env, 0, True, False, (x1, y), self)
        self.sink2 = Node(self.env, 1, True, False, (x2, y), self)
        self.nodes.extend([self.sink1, self.sink2])

        # Place static nodes (luci) evenly along the four walls
        per_wall = m // 4
        extra = m % 4
        idx = 2
        margin = 0.5
        w, h = self.width, self.height

        # Top wall (left to right)
        for i in range(per_wall + (1 if extra > 0 else 0)):
            x = margin + i * (w - 2*margin) / (per_wall + (1 if extra > 0 else 0) - 1) if per_wall + (1 if extra > 0 else 0) > 1 else w/2
            y = margin
            self.nodes.append(Node(self.env, idx, False, False, (x, y), self))
            idx += 1
        # Right wall (top to bottom)
        for i in range(per_wall + (1 if extra > 1 else 0)):
            x = w - margin
            y = margin + i * (h - 2*margin) / (per_wall + (1 if extra > 1 else 0) - 1) if per_wall + (1 if extra > 1 else 0) > 1 else h/2
            self.nodes.append(Node(self.env, idx, False, False, (x, y), self))
            idx += 1
        # Bottom wall (right to left)
        for i in range(per_wall + (1 if extra > 2 else 0)):
            x = w - margin - i * (w - 2*margin) / (per_wall + (1 if extra > 2 else 0) - 1) if per_wall + (1 if extra > 2 else 0) > 1 else w/2
            y = h - margin
            self.nodes.append(Node(self.env, idx, False, False, (x, y), self))
            idx += 1
        # Left wall (bottom to top)
        for i in range(per_wall):
            x = margin
            y = h - margin - i * (h - 2*margin) / (per_wall - 1) if per_wall > 1 else h/2
            self.nodes.append(Node(self.env, idx, False, False, (x, y), self))
            idx += 1

        # central light inside central rectangle center
        cx = (self.central_rect[0] + self.central_rect[2]) / 2
        cy = (self.central_rect[1] + self.central_rect[3]) / 2
        self.nodes.append(Node(self.env, idx, False, False, (cx, cy), self))
        idx += 1

        # 4 visitatori mobili all'outer perimeter, all at least 1m apart
        mobile_positions = []
        for j in range(n):
            for attempt in range(100):
                pos = Node.pick_outer_start(self)
                # Ensure at least 1m from other mobile positions
                if all(math.hypot(pos[0]-mp[0], pos[1]-mp[1]) >= 1.0 for mp in mobile_positions):
                    mobile_positions.append(pos)
                    break
            self.nodes.append(Node(self.env, idx, False, True, mobile_positions[-1], self))
            idx += 1

    def update_neighbors(self):
        for n in self.nodes: n.neighbors.clear()
        for i in range(len(self.nodes)):
            for j in range(i+1,len(self.nodes)):
                n1,n2=self.nodes[i],self.nodes[j]
                if math.hypot(n1.x-n2.x,n1.y-n2.y)<=Node.COMM_RANGE:
                    n1.neighbors.append(n2); n2.neighbors.append(n1)

    def step(self, dt=0.1): self.env.run(until=self.env.now+dt)

# -----------------------
# GUI
# -----------------------
class ShowView(QGraphicsView):
    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing)

class MainWindow(QMainWindow):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.setWindowTitle("Showroom BLE Mesh")
        self.resize(1000, 800)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        self.scene = QGraphicsScene(0, 0, engine.width*60, engine.height*60)
        self.view = ShowView(self.scene)
        layout.addWidget(self.view)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        dock = QDockWidget("Log", self)
        dock.setWidget(self.log)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)
        side = QVBoxLayout()
        btn = QPushButton("Start")
        btn.clicked.connect(self.start)
        side.addWidget(btn)
        layout.addLayout(side)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update)
        self.draw()

    def start(self):
        self.timer.start(50)

    def update(self):
        self.engine.step()
        self.draw()
        while self.engine.logger.entries:
            self.log.appendPlainText(self.engine.logger.entries.pop(0))

    def draw(self):
        self.scene.clear()
        # perimetro esterno
        self.scene.addRect(0, 0, self.engine.width*60, self.engine.height*60,
                           QPen(Qt.darkGray))
        # rettangolo centrale
        x1, y1, x2, y2 = self.engine.central_rect
        pen = QPen(Qt.darkGray)
        brush = QBrush(Qt.lightGray)
        self.scene.addRect(x1*60, y1*60,
                           (x2-x1)*60, (y2-y1)*60,
                           pen, brush)
        # nodi
        for n in self.engine.nodes:
            if n.is_sink:
                col = 'red'
            elif n.is_mobile:
                col = 'green'
            else:
                col = 'blue'

            # Draw tiny black rectangle behind every static node except the central one
            if not n.is_sink and not n.is_mobile:
                # Central node: skip (assume last static node is central)
                cx = (self.engine.central_rect[0] + self.engine.central_rect[2]) / 2
                cy = (self.engine.central_rect[1] + self.engine.central_rect[3]) / 2
                if not (abs(n.x - cx) < 1e-3 and abs(n.y - cy) < 1e-3):
                    # Compute direction from node to center
                    dx = cx - n.x
                    dy = cy - n.y
                    length = math.hypot(dx, dy)
                    if length == 0:
                        ux, uy = 0, 0
                    else:
                        ux, uy = dx/length, dy/length

                    # Place black rectangle exactly on the wall (project from center toward wall)
                    w, h = self.engine.width, self.engine.height
                    m = Node.MARGIN_EXT
                    # Find intersection with wall
                    if abs(n.y - m) < 1e-2:  # top wall
                        bx, by = n.x, m
                    elif abs(n.y - (h - m)) < 1e-2:  # bottom wall
                        bx, by = n.x, h - m
                    elif abs(n.x - m) < 1e-2:  # left wall
                        bx, by = m, n.y
                    elif abs(n.x - (w - m)) < 1e-2:  # right wall
                        bx, by = w - m, n.y
                    else:
                        bx, by = n.x, n.y  # fallback

                    rect_w = 6  # pixels
                    rect_h = 6
                    self.scene.addRect(bx*60 - rect_w/2, by*60 - rect_h/2, rect_w, rect_h,
                                       QPen(Qt.black), QBrush(Qt.black))

                    # If light is ON, draw a transparent cone of light pointing toward the center
                    if n.light:
                        from PyQt5.QtGui import QPolygonF
                        # Cone parameters
                        cone_length = 90  # pixels
                        cone_angle = math.radians(60)  # 60 degree cone
                        # The cone points toward the center
                        center_x = bx*60
                        center_y = by*60
                        angle_to_center = math.atan2(uy, ux)
                        angle0 = angle_to_center - cone_angle/2
                        angle1 = angle_to_center + cone_angle/2
                        p0 = QPointF(center_x, center_y)
                        p1 = QPointF(center_x + cone_length * math.cos(angle0),
                                     center_y + cone_length * math.sin(angle0))
                        p2 = QPointF(center_x + cone_length * math.cos(angle1),
                                     center_y + cone_length * math.sin(angle1))
                        poly = QPolygonF([p0, p1, p2])
                        light_brush = QBrush(QColor(255, 255, 100, 80))  # yellowish, transparent
                        self.scene.addPolygon(poly, QPen(Qt.NoPen), light_brush)

            pen = QPen(QColor('yellow') if n.light else Qt.black,
                       2 if n.light else 1)
            brush = QBrush(QColor(col))
            r = 6
            self.scene.addEllipse(n.x*60 - r, n.y*60 - r, 2*r, 2*r,
                                  pen, brush)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    eng = SimulationEngine()
    w = MainWindow(eng)
    w.show()
    sys.exit(app.exec_())
