# engine.py

import simpy
import random
import math
from node import Node
from logger import Logger

class SimulationEngine:
    """
    The SimulationEngine constructs and runs the SimPy simulation.
    It creates:
      - 2 sink nodes (static, red)
      - Static mesh nodes (blue), placed randomly in a central sub-area with a non-overlap constraint
      - Mobile phone nodes (green), placed randomly and moving
    After placement, it ensures each static node has at least one neighbor (connectivity)
    while preserving the minimum distance constraint.
    """
    def __init__(self,
                 num_mesh_nodes=16,
                 num_mobile_nodes=3,
                 area_width=200,
                 area_height=200,
                 sink_positions=None,
                 min_dist=14.0):
        """
        - num_mesh_nodes: number of static mesh nodes (excluding sinks and phones)
        - num_mobile_nodes: number of mobile phone nodes
        - area_width/area_height: simulation area
        - sink_positions: list of (x,y) tuples for sink locations. If None,
                          two default sinks are placed at (width/3,height/2) and (2*width/3,height/2).
        - min_dist: minimum center-to-center distance between any two static nodes
                    (so circle radius=6 does not overlap; 6+6=12, we use a small buffer so 14).
        """
        self.env = simpy.Environment()
        self.logger = Logger()
        self.mesh_count = num_mesh_nodes
        self.mobile_count = num_mobile_nodes
        self.width = area_width
        self.height = area_height
        self.MIN_DIST = min_dist

        # Default sink positions if none provided
        if sink_positions is None:
            sink_positions = [
                (area_width * 0.33, area_height * 0.5),
                (area_width * 0.66, area_height * 0.5)
            ]
        self.sink_positions = sink_positions

        self.nodes = []       # List of all Node objects
        self.node_map = {}    # ID -> Node

        # Place sinks and mesh nodes with non-overlap; then phones
        self._create_nodes()

        # Compute neighbors once
        self.update_neighbors()

        # Ensure each static node has >=1 neighbor, repairing if necessary (while preserving min-dist)
        self._ensure_each_has_neighbor()

        # Final neighbor recompute
        self.update_neighbors()

    def _create_nodes(self):
        """
        Instantiate Node objects in three phases:
          1. Place sink nodes at given positions, enforcing min-dist among sinks.
          2. Place static mesh nodes randomly in a central sub-area, enforcing min-dist from all other static nodes.
          3. Place mobile phone nodes randomly in full area (no min-dist requirement for phones).
        """
        node_id = 0
        static_positions = []  # Keep track of (x,y) of placed static nodes (sinks + mesh)

        # 1) Sink nodes
        for pos in self.sink_positions:
            x, y = pos
            # If it's the first sink, accept as is; otherwise, ensure it's min-dist from previous sinks
            placed = False
            for attempt in range(50):
                if not static_positions:
                    placed = True
                    break
                # Check distance to all existing static positions
                good = True
                for (sx, sy) in static_positions:
                    if math.hypot(x - sx, y - sy) < self.MIN_DIST:
                        good = False
                        break
                if good:
                    placed = True
                    break
                # Otherwise jitter slightly around the intended sink location
                x = pos[0] + random.uniform(-self.MIN_DIST, self.MIN_DIST)
                y = pos[1] + random.uniform(-self.MIN_DIST, self.MIN_DIST)
                x = max(0, min(self.width, x))
                y = max(0, min(self.height, y))
            # If we never found a conflict-free sink placement in 50 tries, just accept the original position
            sink = Node(env=self.env,
                        node_id=node_id,
                        is_sink=True,
                        is_mobile=False,
                        init_pos=(x, y),
                        engine=self)
            self.nodes.append(sink)
            self.node_map[node_id] = sink
            static_positions.append((x, y))
            node_id += 1

        # 2) Static mesh nodes: rejection sampling in a central sub-area
        sub_w = 80
        sub_h = 80
        x0 = (self.width - sub_w) / 2
        y0 = (self.height - sub_h) / 2
        for _ in range(self.mesh_count):
            placed = False
            for attempt in range(200):
                x = random.uniform(x0, x0 + sub_w)
                y = random.uniform(y0, y0 + sub_h)
                # Check min-dist against all placed static_positions
                good = True
                for (sx, sy) in static_positions:
                    if math.hypot(x - sx, y - sy) < self.MIN_DIST:
                        good = False
                        break
                if good:
                    placed = True
                    break
            # If we failed to find it after many tries, simply snap it near a random existing static node, outside min-dist zone
            if not placed:
                # pick random existing static, then offset by min_dist on a random angle
                (ox, oy) = random.choice(static_positions)
                angle = random.uniform(0, 2 * math.pi)
                x = ox + self.MIN_DIST * math.cos(angle)
                y = oy + self.MIN_DIST * math.sin(angle)
                x = max(0, min(self.width, x))
                y = max(0, min(self.height, y))
                # If that still collides, we accept some possible slight overlap (rare)
            mesh_node = Node(env=self.env,
                             node_id=node_id,
                             is_sink=False,
                             is_mobile=False,
                             init_pos=(x, y),
                             engine=self)
            self.nodes.append(mesh_node)
            self.node_map[node_id] = mesh_node
            static_positions.append((x, y))
            node_id += 1

        # 3) Mobile phone nodes anywhere in the full area
        for _ in range(self.mobile_count):
            x = random.uniform(0, self.width)
            y = random.uniform(0, self.height)
            mobile = Node(env=self.env,
                          node_id=node_id,
                          is_sink=False,
                          is_mobile=True,
                          init_pos=(x, y),
                          engine=self)
            self.nodes.append(mobile)
            self.node_map[node_id] = mobile
            node_id += 1

    def update_neighbors(self):
        """
        Recompute neighbors for all nodes based on COMM_RANGE.
        Called whenever positions change (e.g. after mobility).
        """
        for node in self.nodes:
            node.neighbors.clear()

        for i, node in enumerate(self.nodes):
            for j in range(i + 1, len(self.nodes)):
                other = self.nodes[j]
                dx = node.x - other.x
                dy = node.y - other.y
                dist = math.hypot(dx, dy)
                if dist <= Node.COMM_RANGE:
                    node.neighbors.append(other)
                    other.neighbors.append(node)

    def _ensure_each_has_neighbor(self):
        """
        For each static node (sinks + mesh), if it has zero neighbors, relocate it so that
        it ends up within COMM_RANGE of at least one other static node. Every relocation
        also respects the minimum distance constraint by retrying.
        """
        static_nodes = [n for n in self.nodes if not n.is_mobile]

        changed = True
        while changed:
            changed = False
            # Recompute neighbors for accurate isolation check
            self.update_neighbors()

            for node in static_nodes:
                if len(node.neighbors) == 0:
                    # Node is isolated: attempt to relocate
                    # Pick a random other static node as an "anchor"
                    candidates = [n for n in static_nodes if n.id != node.id]
                    if not candidates:
                        continue
                    anchor = random.choice(candidates)

                    # Try multiple offsets around anchor, at distance slightly < COMM_RANGE
                    for attempt in range(50):
                        angle = random.uniform(0, 2 * math.pi)
                        radius = Node.COMM_RANGE * 0.8
                        new_x = anchor.x + radius * math.cos(angle)
                        new_y = anchor.y + radius * math.sin(angle)
                        # Clip to area
                        new_x = max(0, min(self.width, new_x))
                        new_y = max(0, min(self.height, new_y))
                        # Check min-dist to all other static nodes
                        good = True
                        for other in static_nodes:
                            if other.id == node.id:
                                continue
                            if math.hypot(new_x - other.x, new_y - other.y) < self.MIN_DIST:
                                good = False
                                break
                        if good:
                            node.x = new_x
                            node.y = new_y
                            changed = True
                            break
                    # If we fail after many attempts, place node directly on anchor's COMM_RANGE circle, ignoring min-dist
                    if not changed:
                        angle = random.uniform(0, 2 * math.pi)
                        node.x = anchor.x + Node.COMM_RANGE * math.cos(angle) * 0.99
                        node.y = anchor.y + Node.COMM_RANGE * math.sin(angle) * 0.99
                        node.x = max(0, min(self.width, node.x))
                        node.y = max(0, min(self.height, node.y))
                        changed = True

            # Loop again if any node was moved

    def step(self, dt=1.0):
        """
        Advance simulation by dt simulated seconds.
        """
        target = self.env.now + dt
        self.env.run(until=target)

    def run(self, until=None):
        """
        Run simulation to completion (if until=None) or until given time.
        """
        self.env.run(until=until)
