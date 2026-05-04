"""
puzzle_tab.py  —  Puzzle Training Tab
=======================================
Serves puzzles from the Lichess puzzle database.

Setup (one-time):
  Download the free CSV from https://database.lichess.org/#puzzles
  (~300MB) and point the app at it via Settings, or let the tab
  download a small sample automatically.

Each puzzle row in the CSV:
  PuzzleId, FEN, Moves, Rating, RatingDeviation, Popularity,
  NbPlays, Themes, GameUrl, OpeningTags
"""

import csv
import os
import random
import chess
import chess.pgn
import io
import requests

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSpinBox, QSizePolicy, QProgressBar,
    QFileDialog, QFrame
)
from PyQt6.QtCore import Qt, QThread, QSettings, QObject, pyqtSignal
from PyQt6.QtGui  import QFont, QColor

from board_widget import BoardWidget

APP_NAME = "ChessMasterPro"
ORG_NAME = "ChessMasterPro"

# Lichess puzzle CSV sample URL (first 10k puzzles, ~2MB)
SAMPLE_CSV_URL = (
    "https://raw.githubusercontent.com/niklasf/chess-puzzles/"
    "main/puzzles.csv"
)

# Fallback: a handful of hardcoded puzzles so the tab works with no CSV
BUILTIN_PUZZLES = [
    # (FEN, moves_uci, rating, themes)
    ("r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4",
     "h5f7", 800, "mate mateIn1"),
    ("6k1/5ppp/8/8/8/8/5PPP/4R1K1 w - - 0 1",
     "e1e8", 900, "mate mateIn1"),
    ("r3k2r/ppp2ppp/2n5/3qp3/1b1P4/2NB1N2/PPP2PPP/R1BQK2R w KQkq - 0 8",
     "d1d2 d5d4 c3e4 d4e4", 1200, "advantage"),
    ("2r3k1/5ppp/p7/1p6/1Pb5/2N5/PP3PPP/R3KB1R b KQ - 0 20",
     "c8c3 b2c3 b5b4", 1400, "advantage"),
    ("r1bq1rk1/ppp2ppp/2np1n2/4p1B1/2B1P3/2NP4/PPP2PPP/R2QK1NR w KQ - 0 7",
     "c4f7 f8f7 d1h5 g8f8 h5f7", 1600, "mate"),
]


# ── Puzzle data class ──────────────────────────────────────────────────────────

class Puzzle:
    def __init__(self, fen: str, moves_uci: str, rating: int, themes: str = ""):
        self.fen       = fen
        self.moves_uci = moves_uci.strip().split()
        self.rating    = rating
        self.themes    = themes

    @property
    def board(self) -> chess.Board:
        return chess.Board(self.fen)


# ── CSV loader worker ──────────────────────────────────────────────────────────

class PuzzleLoader(QObject):
    """Loads puzzles from a CSV file in a background thread."""

    finished = pyqtSignal(list)   # list[Puzzle]
    error    = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, csv_path: str, rating_min: int, rating_max: int,
                 count: int = 200):
        super().__init__()
        self._path       = csv_path
        self._rating_min = rating_min
        self._rating_max = rating_max
        self._count      = count

    def run(self):
        try:
            self.progress.emit("Loading puzzles from CSV…")
            puzzles = []
            with open(self._path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        rating = int(row.get("Rating", 0))
                        if not (self._rating_min <= rating <= self._rating_max):
                            continue
                        puzzles.append(Puzzle(
                            fen       = row["FEN"],
                            moves_uci = row["Moves"],
                            rating    = rating,
                            themes    = row.get("Themes", ""),
                        ))
                    except Exception:
                        continue
            random.shuffle(puzzles)
            self.progress.emit(f"Loaded {len(puzzles)} puzzles.")
            self.finished.emit(puzzles[:self._count])
        except Exception as e:
            self.error.emit(str(e))


# ── Puzzle Tab ─────────────────────────────────────────────────────────────────

class PuzzleTab(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings   = QSettings(ORG_NAME, APP_NAME)
        self._puzzles    : list[Puzzle] = []
        self._puzzle_idx : int          = -1
        self._current    : Puzzle | None = None
        self._move_idx   : int          = 0    # index into puzzle moves
        self._solved     : bool         = False
        self._failed     : bool         = False
        self._thread     : QThread | None = None
        self._worker     = None

        self._build_ui()
        self._load_builtin()

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 8, 16)
        root.setSpacing(12)

        # ── Left: board ────────────────────────────────────────────────────
        left = QVBoxLayout()
        left.setSpacing(8)

        # Top controls
        top = QHBoxLayout()

        self.load_csv_btn = QPushButton("📂 Load Puzzle CSV")
        self.load_csv_btn.clicked.connect(self._load_csv)
        top.addWidget(self.load_csv_btn)

        top.addSpacing(10)
        rating_lbl = QLabel("Rating:")
        rating_lbl.setStyleSheet("color:#8a7a5a;")
        top.addWidget(rating_lbl)

        self.min_spin = QSpinBox()
        self.min_spin.setRange(400, 3000)
        self.min_spin.setValue(1000)
        self.min_spin.setFixedWidth(70)
        top.addWidget(self.min_spin)

        dash = QLabel("–")
        dash.setStyleSheet("color:#555;")
        top.addWidget(dash)

        self.max_spin = QSpinBox()
        self.max_spin.setRange(400, 3000)
        self.max_spin.setValue(1800)
        self.max_spin.setFixedWidth(70)
        top.addWidget(self.max_spin)

        top.addStretch()
        left.addLayout(top)

        # Puzzle info
        self.info_lbl = QLabel("Puzzle training — find the best move!")
        self.info_lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.info_lbl.setStyleSheet("color:#c9a96e;")
        left.addWidget(self.info_lbl)

        self.theme_lbl = QLabel("")
        self.theme_lbl.setStyleSheet("color:#6a5a3a; font-size:11px;")
        left.addWidget(self.theme_lbl)

        # Board
        self.board_w = BoardWidget()
        self.board_w.move_made.connect(self._on_move)
        left.addWidget(self.board_w)

        # Result banner
        self.result_lbl = QLabel("")
        self.result_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        self.result_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_lbl.setVisible(False)
        left.addWidget(self.result_lbl)

        # Nav buttons
        nav = QHBoxLayout()
        btn_style = (
            "QPushButton{background:#2e2818;color:#c9a96e;border:1px solid #5a4a2a;"
            "border-radius:5px;padding:7px 18px;font-weight:600;}"
            "QPushButton:hover{background:#3a3020;}"
            "QPushButton:disabled{color:#3a3020;border-color:#2a2010;}"
        )
        self.next_btn = QPushButton("Next Puzzle  ▶")
        self.next_btn.setStyleSheet(btn_style)
        self.next_btn.clicked.connect(self._next_puzzle)
        nav.addWidget(self.next_btn)

        self.hint_btn = QPushButton("💡 Hint")
        self.hint_btn.setStyleSheet(btn_style)
        self.hint_btn.clicked.connect(self._show_hint)
        nav.addWidget(self.hint_btn)

        self.solution_btn = QPushButton("👁 Show Solution")
        self.solution_btn.setStyleSheet(btn_style)
        self.solution_btn.clicked.connect(self._show_solution)
        nav.addWidget(self.solution_btn)

        nav.addStretch()
        self.rating_lbl = QLabel("")
        self.rating_lbl.setStyleSheet("color:#6a5a3a; font-size:12px;")
        nav.addWidget(self.rating_lbl)

        left.addLayout(nav)
        root.addLayout(left, stretch=3)

        # ── Right: stats panel ─────────────────────────────────────────────
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(12)

        stats_title = QLabel("SESSION")
        stats_title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        stats_title.setStyleSheet("color:#555; letter-spacing:1px;")
        right.addWidget(stats_title)

        self._solved_count  = 0
        self._failed_count  = 0
        self._attempted     = 0

        self.solved_lbl = QLabel("Solved:  0")
        self.solved_lbl.setStyleSheet("color:#7ec845; font-size:13px;")
        right.addWidget(self.solved_lbl)

        self.failed_lbl = QLabel("Failed:  0")
        self.failed_lbl.setStyleSheet("color:#ef5350; font-size:13px;")
        right.addWidget(self.failed_lbl)

        self.acc_lbl = QLabel("Accuracy:  —")
        self.acc_lbl.setStyleSheet("color:#c9a96e; font-size:13px;")
        right.addWidget(self.acc_lbl)

        right.addSpacing(20)

        # Puzzle queue info
        self.queue_lbl = QLabel("Queue: 0 puzzles")
        self.queue_lbl.setStyleSheet("color:#6a5a3a; font-size:11px;")
        right.addWidget(self.queue_lbl)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet(
            "QProgressBar{background:#252018;border:1px solid #3a3020;"
            "border-radius:4px;}"
            "QProgressBar::chunk{background:#c9a96e;border-radius:4px;}"
        )
        right.addWidget(self.progress_bar)

        right.addStretch()
        root.addLayout(right, stretch=1)

    # ── Puzzle loading ─────────────────────────────────────────────────────────

    def _load_builtin(self):
        """Load the small built-in puzzle set."""
        self._puzzles = [
            Puzzle(fen, moves, rating, themes)
            for fen, moves, rating, themes in BUILTIN_PUZZLES
        ]
        random.shuffle(self._puzzles)
        self.queue_lbl.setText(f"Queue: {len(self._puzzles)} built-in puzzles")
        self._puzzle_idx = -1
        self._next_puzzle()

    def _load_csv(self):
        csv_path = self._settings.value("puzzle_csv_path", "")
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Lichess Puzzle CSV", csv_path,
            "CSV Files (*.csv);;All Files (*)"
        )
        if not path:
            return
        self._settings.setValue("puzzle_csv_path", path)
        self._load_csv_file(path)

    def _load_csv_file(self, path: str):
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)   # indeterminate

        self._thread = QThread()
        self._worker = PuzzleLoader(
            path,
            rating_min = self.min_spin.value(),
            rating_max = self.max_spin.value(),
            count      = 300,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.queue_lbl.setText)
        self._worker.finished.connect(self._on_puzzles_loaded)
        self._worker.error.connect(lambda e: self.queue_lbl.setText(f"Error: {e}"))
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(lambda: self.progress_bar.setVisible(False))
        self._thread.start()

    def _on_puzzles_loaded(self, puzzles: list):
        self._puzzles    = puzzles
        self._puzzle_idx = -1
        self.queue_lbl.setText(f"Queue: {len(puzzles)} puzzles")
        self._next_puzzle()

    # ── Puzzle flow ────────────────────────────────────────────────────────────

    def _next_puzzle(self):
        if not self._puzzles:
            self.info_lbl.setText("No puzzles loaded. Load a CSV or use built-ins.")
            return

        self._puzzle_idx = (self._puzzle_idx + 1) % len(self._puzzles)
        self._current    = self._puzzles[self._puzzle_idx]
        self._move_idx   = 0
        self._solved     = False
        self._failed     = False

        board = self._current.board
        # The first move in the puzzle is played by the opponent —
        # apply it automatically so the player faces the resulting position
        if self._current.moves_uci:
            first_move = chess.Move.from_uci(self._current.moves_uci[0])
            board.push(first_move)
            self._move_idx = 1

        self.board_w.set_board(board)
        self.board_w.set_interactive(True)
        self.board_w._flipped = (board.turn == chess.BLACK)

        # UI
        side = "White" if board.turn == chess.WHITE else "Black"
        self.info_lbl.setText(f"Find the best move for {side}!")
        self.theme_lbl.setText(
            "Themes: " + self._current.themes if self._current.themes else ""
        )
        self.rating_lbl.setText(f"Rating: {self._current.rating}")
        self.result_lbl.setVisible(False)
        self.hint_btn.setEnabled(True)
        self.solution_btn.setEnabled(True)

    def _on_move(self, move: chess.Move):
        if self._solved or self._failed or not self._current:
            return

        expected_uci = self._current.moves_uci[self._move_idx] \
            if self._move_idx < len(self._current.moves_uci) else None

        if move.uci() == expected_uci:
            self._move_idx += 1

            # Apply opponent's response if there are more moves
            if self._move_idx < len(self._current.moves_uci):
                opp_move = chess.Move.from_uci(
                    self._current.moves_uci[self._move_idx]
                )
                self.board_w.push_move(opp_move)
                self._move_idx += 1

                if self._move_idx >= len(self._current.moves_uci):
                    self._mark_solved()
            else:
                self._mark_solved()
        else:
            self._mark_failed()

    def _mark_solved(self):
        self._solved        = True
        self._solved_count += 1
        self._attempted    += 1
        self.board_w.set_interactive(False)
        self.result_lbl.setText("✔  Correct!  Puzzle solved.")
        self.result_lbl.setStyleSheet(
            "color:#7ec845; font-size:14px; font-weight:700;"
        )
        self.result_lbl.setVisible(True)
        self._update_stats()

    def _mark_failed(self):
        self._failed        = True
        self._failed_count += 1
        self._attempted    += 1
        self.board_w.set_interactive(False)
        self.result_lbl.setText("✘  Incorrect.  Click 'Show Solution' to see the answer.")
        self.result_lbl.setStyleSheet(
            "color:#ef5350; font-size:13px; font-weight:700;"
        )
        self.result_lbl.setVisible(True)
        self._update_stats()

    def _show_hint(self):
        if not self._current or self._move_idx >= len(self._current.moves_uci):
            return
        move_uci = self._current.moves_uci[self._move_idx]
        move     = chess.Move.from_uci(move_uci)
        board    = self.board_w.board
        try:
            san = board.san(move)
        except Exception:
            san = move_uci
        from_sq = chess.square_name(move.from_square)
        self.info_lbl.setText(f"💡 Hint: piece on {from_sq}")

    def _show_solution(self):
        if not self._current:
            return
        # Replay remaining solution moves on the board
        self.board_w.set_interactive(False)
        self._failed = True
        board = self.board_w.board
        san_moves = []
        for uci in self._current.moves_uci[self._move_idx:]:
            try:
                move = chess.Move.from_uci(uci)
                san_moves.append(board.san(move))
                board.push(move)
            except Exception:
                san_moves.append(uci)
        self.board_w.set_board(board)
        self.info_lbl.setText(
            "Solution: " + "  ".join(san_moves)
        )
        self.result_lbl.setVisible(False)

    def _update_stats(self):
        self.solved_lbl.setText(f"Solved:  {self._solved_count}")
        self.failed_lbl.setText(f"Failed:  {self._failed_count}")
        if self._attempted:
            acc = self._solved_count / self._attempted * 100
            self.acc_lbl.setText(f"Accuracy:  {acc:.0f}%")