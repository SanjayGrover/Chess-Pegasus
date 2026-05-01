"""
test_board.py  —  Quick visual test for board_widget.py
Run:  python test_board.py
"""
import sys
import chess
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QPushButton, QWidget
from PyQt6.QtCore import Qt
from board_widget import BoardWidget


class TestWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Board Widget Test")
        self.setStyleSheet("background:#1a1a1a; color:#e8d5b0;")
        self.resize(700, 760)

        central = QWidget()
        layout  = QVBoxLayout(central)
        layout.setContentsMargins(20, 20, 20, 20)

        self.board_w = BoardWidget()
        self.board_w.move_made.connect(lambda m: print("Move:", m.uci()))
        layout.addWidget(self.board_w)

        # Control buttons
        btn_row = QHBoxLayout()
        for label, fn in [
            ("Flip",  self.board_w.flip),
            ("Undo",  self.board_w.undo_move),
            ("Reset", self._reset),
            ("Kasprov Position", self._load_sample),
        ]:
            b = QPushButton(label)
            b.setStyleSheet(
                "QPushButton{background:#2e2818;color:#c9a96e;border:1px solid #5a4a2a;"
                "border-radius:5px;padding:7px 16px;font-weight:600;}"
                "QPushButton:hover{background:#3a3020;}"
            )
            b.clicked.connect(fn)
            btn_row.addWidget(b)
        layout.addLayout(btn_row)

        self.setCentralWidget(central)

    def _reset(self):
        self.board_w.set_board(chess.Board())

    def _load_sample(self):
        # Interesting middlegame position
        board = chess.Board("r1bqk2r/pp2bppp/2nppn2/8/3NP3/2N1B3/PPP1BPPP/R2QK2R w KQkq - 0 8")
        self.board_w.set_board(board)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w   = TestWindow()
    w.show()
    sys.exit(app.exec())