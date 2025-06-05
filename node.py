# node.py

import simpy
import random
import math
from packets import Packet

class Node:
    """
    A BLE mesh node for RouMBLE simulation. Supports:
      - Static placement (if is_mobile=False) or mobility (if is_mobile=True).
      - Sink-oriented BOM flooding for routing table construction.
      - Hop-limited RMS (data) flooding toward sinks.
      - Mock IPv6 address (string).
      - Logging via the shared Logger instance.
    """
    COMM_RANGE = 30.0       # communication radius (units)
    MOVE_INTERVAL = 5.0     # seconds between movement steps for mobile nodes
    MOVE_DISTANCE = 10.0    # max distance per move for mobile nodes
    BOM_INTERVAL = 20.0     # seconds between sink BOM broadcasts
    RMS_INTERVAL = 15.0     # average seconds between RMS packet generation (per non-sink)
    TX_DELAY = 0.05         # time to 'transmit' a packet (simulated)
    RX_DELAY = 0.01         # time to 'receive' a packet (simulated)
    MAX_HOPS = 3            # default hop limit for RMS

    def __init__(self, env, node_id, is_sink, is_mobile, init_pos, engine):
        """
        env: SimPy Environment
        node_id: integer ID
        is_sink: bool, True if this node is a sink
        is_mobile: bool, True if this node moves (phones), else static
        init_pos: (x, y) initial position
        engine: reference to SimulationEngine
        """
        self.env = env
        self.id = node_id
        self.is_sink = is_sink
        self.is_mobile = is_mobile
        self.engine = engine

        # Assign a mock IPv6 address
        self.ipv6 = f"fe80::1:{node_id:04x}"

        # Position
        self.x, self.y = init_pos

        # Neighbors: recomputed by engine.update_neighbors()
        self.neighbors = []

        # Routing table: sink_id -> (next_hop_id, hop_distance, seq)
        self.routing_table = {}
        # For BOM sequence checking: sink_id -> highest seq seen
        self.best_seq = {}
        # RMS duplicate suppression: set of (origin, seq)
        self.seen_rms = set()

        # Per-node sequence counter for packets it generates
        self.seq_num = 0

        # Energy and counters (not decremented here, but tracked)
        self.energy = 100.0
        self.tx_count = 0
        self.rx_count = 0

        # Start processes:
        if self.is_sink:
            env.process(self._sink_bom_process())
        else:
            env.process(self._generate_rms_process())

        # Only mobile nodes run mobility; sinks and static relays do not move
        if self.is_mobile:
            env.process(self._mobility_process())

    def _mobility_process(self):
        """
        Periodically move to a new random location within the area.
        After moving, notify engine to update neighbor lists.
        """
        while True:
            yield self.env.timeout(Node.MOVE_INTERVAL)
            angle = random.uniform(0, 2 * math.pi)
            dx = Node.MOVE_DISTANCE * math.cos(angle)
            dy = Node.MOVE_DISTANCE * math.sin(angle)
            new_x = self.x + dx
            new_y = self.y + dy
            self.x = max(0, min(self.engine.width, new_x))
            self.y = max(0, min(self.engine.height, new_y))
            # Notify engine to recompute neighbors
            self.engine.update_neighbors()

    def _sink_bom_process(self):
        """
        Sink node periodically sends BOM packets to flood the network and build routes.
        """
        while True:
            yield self.env.timeout(Node.BOM_INTERVAL)
            self.seq_num += 1
            bom = Packet(
                pkt_type='BOM',
                src=self.id,
                sink_id=self.id,
                seq=self.seq_num,
                hop_count=0,
                origin=self.id,
                timestamp=self.env.now
            )
            self.logger().record_control_sent()
            # Log event: from sink to all neighbors (use -1 to denote broadcast)
            self.logger().log_event(self.env.now, 'BOM', self.id, -1)
            self.env.process(self._broadcast(bom))

    def _generate_rms_process(self):
        """
        Non-sink nodes periodically generate RMS data packets.
        They attempt to send them to a sink via the routing table.
        If no route exists, broadcast as fallback.
        """
        while True:
            interval = random.expovariate(1.0 / Node.RMS_INTERVAL)
            yield self.env.timeout(interval)
            self.seq_num += 1
            rms = Packet(
                pkt_type='RMS',
                src=self.id,
                sink_id=None,
                seq=self.seq_num,
                hop_count=Node.MAX_HOPS,
                origin=self.id,
                timestamp=self.env.now
            )
            self.logger().record_data_sent()
            self.logger().log_event(self.env.now, 'RMS_GEN', self.id, -1)
            self._send_rms(rms)

    def _send_rms(self, packet):
        """
        Attempt to forward an RMS to a sink using routing table.
        If no route exists, broadcast it.
        """
        if self.routing_table:
            # Pick sink with smallest hop count
            sink_id, (next_hop, dist, _) = min(
                self.routing_table.items(), key=lambda kv: kv[1][1]
            )
            packet.sink_id = sink_id
            packet.hop_count = dist + 1
            # Unicast to that neighbor
            for nb in self.neighbors:
                if nb.id == next_hop:
                    self.tx_count += 1
                    self.logger().log_event(self.env.now, 'RMS_UNI', self.id, nb.id)
                    self.env.process(self._deliver(nb, packet))
                    return
        # If no route or neighbor missing, broadcast
        self.logger().log_event(self.env.now, 'RMS_BRD', self.id, -1)
        self.env.process(self._broadcast(packet))

    def _broadcast(self, packet):
        """
        Broadcast a packet to all current neighbors after TX_DELAY.
        """
        yield self.env.timeout(Node.TX_DELAY)
        for nb in list(self.neighbors):
            copy = Packet(
                pkt_type=packet.pkt_type,
                src=self.id,
                sink_id=packet.sink_id,
                seq=packet.seq,
                hop_count=packet.hop_count,
                origin=packet.origin,
                timestamp=packet.timestamp
            )
            self.tx_count += 1
            self.env.process(nb.receive(copy))

    def _deliver(self, neighbor, packet):
        """
        Deliver a packet to a specific neighbor after TX_DELAY. Used for unicast.
        """
        yield self.env.timeout(Node.TX_DELAY)
        copy = Packet(
            pkt_type=packet.pkt_type,
            src=self.id,
            sink_id=packet.sink_id,
            seq=packet.seq,
            hop_count=packet.hop_count,
            origin=packet.origin,
            timestamp=packet.timestamp
        )
        self.tx_count += 1
        self.env.process(neighbor.receive(copy))

    def receive(self, packet):
        """
        SimPy process: a node receives a packet after RX_DELAY, then handles it.
        """
        yield self.env.timeout(Node.RX_DELAY)
        self.rx_count += 1
        if packet.pkt_type == 'BOM':
            self._handle_bom(packet)
        elif packet.pkt_type == 'RMS':
            self._handle_rms(packet)

    def _handle_bom(self, packet):
        """
        Process an incoming BOM (routing beacon). Update routing table if necessary
        and rebroadcast if improved.
        """
        sink = packet.sink_id
        seq = packet.seq
        hop = packet.hop_count + 1
        prev_seq = self.best_seq.get(sink, -1)
        prev_entry = self.routing_table.get(sink)
        prev_hop = prev_entry[1] if prev_entry else math.inf

        if seq > prev_seq or hop < prev_hop:
            self.routing_table[sink] = (packet.src, hop, seq)
            self.best_seq[sink] = seq
            self.logger().record_routing_update()
            self.logger().log_event(self.env.now, 'BOM_FWD', self.id, -1)
            new_bom = Packet(
                pkt_type='BOM',
                src=self.id,
                sink_id=sink,
                seq=seq,
                hop_count=hop,
                origin=packet.origin,
                timestamp=packet.timestamp
            )
            self.logger().record_control_sent()
            self.env.process(self._broadcast(new_bom))

    def _handle_rms(self, packet):
        """
        Process incoming RMS (data) packet. If destined to this node (a sink),
        record delivery; otherwise forward if TTL allows.
        """
        key = (packet.origin, packet.seq)
        if key in self.seen_rms:
            return
        self.seen_rms.add(key)

        if self.is_sink and packet.sink_id == self.id:
            latency = self.env.now - packet.timestamp
            hops_traveled = packet.hop_count
            self.logger().record_data_delivered(latency, hops_traveled)
            self.logger().log_event(self.env.now, 'RMS_DEL', packet.src, self.id)
            return

        if packet.hop_count > 1:
            packet.hop_count -= 1
            self._send_rms(packet)

    def logger(self):
        """Return the shared Logger."""
        return self.engine.logger
