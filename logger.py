# logger.py

class Logger:
    """
    Collects simulation-wide metrics and event logs.
    Metrics:
      - control_sent: number of BOM (control) packets sent
      - data_sent:   number of RMS (data) packets generated/sent
      - data_delivered: number of RMS packets received at sinks
      - delays: list of end-to-end latencies for delivered RMS
      - hops: list of hop counts for delivered RMS
      - routing_updates: number of routing table updates performed
    Event Log:
      - entries: list of strings describing packet events (time, type, src, dst)
    """
    def __init__(self):
        self.control_sent = 0
        self.data_sent = 0
        self.data_delivered = 0
        self.delays = []
        self.hops = []
        self.routing_updates = 0
        self.entries = []

    def record_control_sent(self):
        self.control_sent += 1

    def record_data_sent(self):
        self.data_sent += 1

    def record_data_delivered(self, latency, hops):
        self.data_delivered += 1
        self.delays.append(latency)
        self.hops.append(hops)

    def record_routing_update(self):
        self.routing_updates += 1

    def log_event(self, time, pkt_type, src, dst):
        """
        Append a log entry. Example: "[3.50s] BOM from Node2 to Node5"
        Use dst=-1 to indicate broadcast ("→All").
        """
        dst_str = f"Node{dst}" if dst != -1 else "All"
        entry = f"[{time:.2f}s] {pkt_type} from Node{src} to {dst_str}"
        self.entries.append(entry)

    def packet_delivery_ratio(self):
        if self.data_sent == 0:
            return 0.0
        return self.data_delivered / self.data_sent

    def avg_latency(self):
        return (sum(self.delays) / len(self.delays)) if self.delays else 0.0

    def avg_hops(self):
        return (sum(self.hops) / len(self.hops)) if self.hops else 0.0

    def overhead_ratio(self):
        if self.data_sent == 0:
            return float('inf') if self.control_sent > 0 else 0.0
        return self.control_sent / self.data_sent

    def get_metrics(self):
        """
        Return a dict of current metrics:
          - pdr (0..1)
          - avg_latency
          - avg_hops
          - control_sent
          - data_sent
          - data_delivered
          - routing_updates
          - overhead
        """
        return {
            'pdr': self.packet_delivery_ratio(),
            'avg_latency': self.avg_latency(),
            'avg_hops': self.avg_hops(),
            'control_sent': self.control_sent,
            'data_sent': self.data_sent,
            'data_delivered': self.data_delivered,
            'routing_updates': self.routing_updates,
            'overhead': self.overhead_ratio()
        }
