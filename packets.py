# packets.py

class Packet:
    """
    A network packet in the RouMBLE simulation. Can be of type 'BOM' (beacon)
    or 'RMS' (data). Fields:
      - pkt_type: 'BOM' or 'RMS'
      - src: Sender node ID (int)
      - sink_id: For BOM, the originating sink ID; for RMS, the destination sink ID.
      - seq: Sequence number (int) to uniquely identify packets.
      - hop_count: Remaining hop count (int). For BOM it's the distance so far; for RMS it's TTL.
      - origin: Originator ID (int). For RMS, this is the original source; for BOM, same as sink_id.
      - timestamp: Simulated time when the packet was created (float).
    """
    def __init__(self, pkt_type, src, sink_id, seq, hop_count=0, origin=None, timestamp=0.0):
        self.pkt_type = pkt_type    # 'BOM' or 'RMS'
        self.src = src              # ID of the node that sent this packet
        self.sink_id = sink_id      # For BOM: the sink; for RMS: destination sink (or None)
        self.seq = seq              # Sequence number
        self.hop_count = hop_count  # For BOM: distance so far; for RMS: TTL
        self.origin = origin if origin is not None else src
        self.timestamp = timestamp  # Creation time in sim seconds

    def __repr__(self):
        return (f"<Packet {self.pkt_type} seq={self.seq} src={self.src} "
                f"sink={self.sink_id} hops={self.hop_count} origin={self.origin}>")
