# main.py

import sys
from PyQt5.QtWidgets import QApplication
from engine import SimulationEngine
from gui import MainWindow

def main():
    # Use fewer static mesh nodes (16) and fewer mobiles (3) for clarity
    NUM_MESH_NODES = 16
    NUM_MOBILE_NODES = 3
    AREA_WIDTH = 200
    AREA_HEIGHT = 200
    # Two sinks at one-third and two-thirds horizontally, centered vertically
    SINK_POSITIONS = [
        (AREA_WIDTH * 0.33, AREA_HEIGHT * 0.5),
        (AREA_WIDTH * 0.66, AREA_HEIGHT * 0.5)
    ]

    engine = SimulationEngine(
        num_mesh_nodes=NUM_MESH_NODES,
        num_mobile_nodes=NUM_MOBILE_NODES,
        area_width=AREA_WIDTH,
        area_height=AREA_HEIGHT,
        sink_positions=SINK_POSITIONS
    )

    app = QApplication(sys.argv)
    window = MainWindow(engine)
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
